#!/usr/bin/env python3
"""Idempotently enable xray traffic statistics in a JSONC config.

Parses the config with a small position-tracking JSONC parser (handles
// and # line comments, /* */ block comments, and trailing commas),
then inserts only what's missing as surgical text edits. The original
formatting and comments are preserved.

Exits 0 if changes were applied, 5 if the config was already complete.
Creates a timestamped .bak only when changes will be written.
"""

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path


WANTED_SERVICES = ["StatsService", "LoggerService", "HandlerService"]
API_LISTEN = "127.0.0.1"
API_PORT = 10085
IND = "  "

EXIT_NO_CHANGES = 5


class Obj:
    __slots__ = ("start", "end", "open_pos", "close_pos", "fields")

    def __init__(self, start, end, open_pos, close_pos, fields):
        self.start = start
        self.end = end
        self.open_pos = open_pos
        self.close_pos = close_pos
        self.fields = fields

    def __contains__(self, key):
        return key in self.fields

    def get(self, key, default=None):
        return self.fields.get(key, default)


class Arr:
    __slots__ = ("start", "end", "open_pos", "close_pos", "items")

    def __init__(self, start, end, open_pos, close_pos, items):
        self.start = start
        self.end = end
        self.open_pos = open_pos
        self.close_pos = close_pos
        self.items = items


class Lit:
    __slots__ = ("start", "end", "value")

    def __init__(self, start, end, value):
        self.start = start
        self.end = end
        self.value = value


class Parser:
    def __init__(self, text):
        self.text = text
        self.pos = 0
        self.n = len(text)

    def _at(self):
        return self.text[self.pos] if self.pos < self.n else ""

    def _skip_ws(self):
        t, n = self.text, self.n
        while self.pos < n:
            c = t[self.pos]
            if c.isspace():
                self.pos += 1
            elif c == "/" and self.pos + 1 < n and t[self.pos + 1] == "/":
                nl = t.find("\n", self.pos)
                self.pos = n if nl == -1 else nl
            elif c == "#":
                nl = t.find("\n", self.pos)
                self.pos = n if nl == -1 else nl
            elif c == "/" and self.pos + 1 < n and t[self.pos + 1] == "*":
                end = t.find("*/", self.pos + 2)
                self.pos = n if end == -1 else end + 2
            else:
                break

    def _parse_string_raw(self):
        start = self.pos
        self.pos += 1
        while self.pos < self.n and self.text[self.pos] != '"':
            if self.text[self.pos] == "\\":
                self.pos += 2
            else:
                self.pos += 1
        self.pos += 1
        end = self.pos
        return start, end, json.loads(self.text[start:end])

    def parse_value(self):
        self._skip_ws()
        c = self._at()
        start = self.pos
        if c == "{":
            return self._parse_object(start)
        if c == "[":
            return self._parse_array(start)
        if c == '"':
            s, e, v = self._parse_string_raw()
            return Lit(s, e, v)
        while self.pos < self.n and self.text[self.pos] not in ",]} \t\n\r":
            self.pos += 1
        s = self.text[start : self.pos]
        if s == "true":
            v = True
        elif s == "false":
            v = False
        elif s == "null":
            v = None
        else:
            try:
                v = int(s)
            except ValueError:
                try:
                    v = float(s)
                except ValueError:
                    v = s
        return Lit(start, self.pos, v)

    def _parse_object(self, start):
        open_pos = self.pos
        self.pos += 1
        fields = {}
        while True:
            self._skip_ws()
            if self._at() == "}":
                close_pos = self.pos
                self.pos += 1
                return Obj(start, self.pos, open_pos, close_pos, fields)
            _, _, key = self._parse_string_raw()
            self._skip_ws()
            self.pos += 1  # ':'
            self._skip_ws()
            fields[key] = self.parse_value()
            self._skip_ws()
            if self._at() == ",":
                self.pos += 1

    def _parse_array(self, start):
        open_pos = self.pos
        self.pos += 1
        items = []
        while True:
            self._skip_ws()
            if self._at() == "]":
                close_pos = self.pos
                self.pos += 1
                return Arr(start, self.pos, open_pos, close_pos, items)
            items.append(self.parse_value())
            self._skip_ws()
            if self._at() == ",":
                self.pos += 1


def parse_jsonc(text):
    p = Parser(text)
    p._skip_ws()
    return p.parse_value()


def lit_value(node, default=None):
    return node.value if isinstance(node, Lit) else default


def plan_inserts(root):
    """Plan surgical inserts to enable stats.

    Returns dict mapping insert position -> {"empty": bool, "items": [str]}.
    "empty" tracks whether the parent object/array was empty before our
    inserts. apply_inserts uses this to decide whether to append a
    trailing comma (to connect to existing content) or not (avoiding a
    trailing comma in a single-item container).
    """
    if not isinstance(root, Obj):
        raise ValueError("Top-level config must be a JSON object")

    inserts = {}

    def add(pos, content, container_empty):
        if pos in inserts:
            inserts[pos]["items"].append(content)
        else:
            inserts[pos] = {"empty": container_empty, "items": [content]}

    fields = root.fields
    root_empty = not fields

    # .stats = {}
    if "stats" not in fields:
        add(root.open_pos + 1, f'\n{IND}"stats": {{}}', root_empty)

    # .api object with tag and services
    api = fields.get("api")
    if api is None:
        svc = ", ".join(f'"{s}"' for s in WANTED_SERVICES)
        block = (
            f'\n{IND}"api": {{'
            f'\n{IND * 2}"tag": "api",'
            f'\n{IND * 2}"services": [{svc}]'
            f"\n{IND}}}"
        )
        add(root.open_pos + 1, block, root_empty)
    elif isinstance(api, Obj):
        api_empty = not api.fields
        if "tag" not in api:
            add(api.open_pos + 1, f'\n{IND * 2}"tag": "api"', api_empty)

        services = api.get("services")
        if services is None:
            svc = ", ".join(f'"{s}"' for s in WANTED_SERVICES)
            add(api.open_pos + 1, f'\n{IND * 2}"services": [{svc}]', api_empty)
        elif isinstance(services, Arr):
            existing = [it.value for it in services.items if isinstance(it, Lit)]
            missing = [s for s in WANTED_SERVICES if s not in existing]
            if missing:
                add_str = ", ".join(f'"{m}"' for m in missing)
                add(services.open_pos + 1, add_str, not services.items)

    # .policy
    policy = fields.get("policy")
    if policy is None:
        block = (
            f'\n{IND}"policy": {{'
            f'\n{IND * 2}"levels": {{'
            f'\n{IND * 3}"0": {{'
            f'\n{IND * 4}"statsUserUplink": true,'
            f'\n{IND * 4}"statsUserDownlink": true'
            f"\n{IND * 3}}}"
            f"\n{IND * 2}}},"
            f'\n{IND * 2}"system": {{'
            f'\n{IND * 3}"statsInboundUplink": false,'
            f'\n{IND * 3}"statsInboundDownlink": false,'
            f'\n{IND * 3}"statsOutboundUplink": true,'
            f'\n{IND * 3}"statsOutboundDownlink": true'
            f"\n{IND * 2}}}"
            f"\n{IND}}}"
        )
        add(root.open_pos + 1, block, root_empty)
    elif isinstance(policy, Obj):
        policy_empty = not policy.fields
        levels = policy.get("levels")
        if levels is None:
            add(
                policy.open_pos + 1,
                f'\n{IND * 2}"levels": {{ "0": {{ "statsUserUplink": true,'
                f' "statsUserDownlink": true }} }}',
                policy_empty,
            )
        elif isinstance(levels, Obj):
            zero = levels.get("0")
            if zero is None:
                add(
                    levels.open_pos + 1,
                    f'\n{IND * 3}"0": {{ "statsUserUplink": true,'
                    f' "statsUserDownlink": true }}',
                    not levels.fields,
                )
            elif isinstance(zero, Obj):
                zero_empty = not zero.fields
                for key in ("statsUserUplink", "statsUserDownlink"):
                    if key not in zero:
                        add(
                            zero.open_pos + 1,
                            f'\n{IND * 4}"{key}": true',
                            zero_empty,
                        )

        system = policy.get("system")
        if system is None:
            add(
                policy.open_pos + 1,
                f'\n{IND * 2}"system": {{ "statsInboundUplink": false,'
                f' "statsInboundDownlink": false, "statsOutboundUplink": true,'
                f' "statsOutboundDownlink": true }}',
                policy_empty,
            )
        elif isinstance(system, Obj):
            system_empty = not system.fields
            for key, want in [
                ("statsInboundUplink", "false"),
                ("statsInboundDownlink", "false"),
                ("statsOutboundUplink", "true"),
                ("statsOutboundDownlink", "true"),
            ]:
                if key not in system:
                    add(
                        system.open_pos + 1,
                        f'\n{IND * 3}"{key}": {want}',
                        system_empty,
                    )

    # .inbounds — ensure dokodemo-door for api
    api_inbound = (
        f'{{ "listen": "{API_LISTEN}", "port": {API_PORT},'
        f' "protocol": "dokodemo-door",'
        f' "settings": {{ "address": "{API_LISTEN}" }}, "tag": "api" }}'
    )
    inbounds = fields.get("inbounds")
    if inbounds is None:
        add(
            root.open_pos + 1,
            f'\n{IND}"inbounds": [\n{IND * 2}{api_inbound}\n{IND}]',
            root_empty,
        )
    elif isinstance(inbounds, Arr):
        has_api = any(
            isinstance(item, Obj) and lit_value(item.get("tag")) == "api"
            for item in inbounds.items
        )
        if not has_api:
            add(
                inbounds.open_pos + 1,
                f"\n{IND * 2}{api_inbound}",
                not inbounds.items,
            )

    # .routing.rules — ensure api routing rule (prepended)
    api_rule = (
        '{ "type": "field", "inboundTag": ["api"], "outboundTag": "api" }'
    )
    routing = fields.get("routing")
    if routing is None:
        add(
            root.open_pos + 1,
            f'\n{IND}"routing": {{ "rules": [{api_rule}] }}',
            root_empty,
        )
    elif isinstance(routing, Obj):
        routing_empty = not routing.fields
        rules = routing.get("rules")
        if rules is None:
            add(
                routing.open_pos + 1,
                f'\n{IND * 2}"rules": [{api_rule}]',
                routing_empty,
            )
        elif isinstance(rules, Arr):
            def is_api_rule(item):
                if not isinstance(item, Obj):
                    return False
                if lit_value(item.get("outboundTag")) != "api":
                    return False
                inbound = item.get("inboundTag")
                return isinstance(inbound, Arr) and any(
                    lit_value(t) == "api" for t in inbound.items
                )

            has_rule = any(is_api_rule(item) for item in rules.items)
            if not has_rule:
                add(
                    rules.open_pos + 1,
                    f"\n{IND * 3}{api_rule}",
                    not rules.items,
                )

    return inserts


def apply_inserts(text, inserts):
    out = []
    i = 0
    for pos in sorted(inserts.keys()):
        out.append(text[i:pos])
        spec = inserts[pos]
        joined = ",".join(spec["items"])
        if not spec["empty"]:
            joined += ","
        out.append(joined)
        i = pos
    out.append(text[i:])
    return "".join(out)


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <config-path>", file=sys.stderr)
        sys.exit(1)

    config_path = Path(sys.argv[1])
    if not config_path.is_file():
        print(f"File not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    text = config_path.read_text()
    root = parse_jsonc(text)
    inserts = plan_inserts(root)

    if not inserts:
        print(f"{config_path}: already configured for stats.")
        sys.exit(EXIT_NO_CHANGES)

    new_text = apply_inserts(text, inserts)

    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    backup = config_path.with_name(config_path.name + f".{ts}.bak")
    shutil.copy(config_path, backup)
    print(f"Backup: {backup}")

    config_path.write_text(new_text)
    n_changes = sum(len(v["items"]) for v in inserts.values())
    print(f"{config_path}: applied {n_changes} change(s).")


if __name__ == "__main__":
    main()
