"""End-to-end tests for enable-stats.py.

Tests invoke the script as a subprocess in a tmp_path workspace so they
exercise the real CLI path (argument parsing, backup creation, exit
codes) without touching the developer's xray config.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "enable-stats.py"

EXIT_CHANGES_APPLIED = 0
EXIT_NO_CHANGES = 5

FULLY_CONFIGURED = """\
{
  "stats": {},
  "api": {
    "tag": "api",
    "services": ["StatsService", "LoggerService", "HandlerService"]
  },
  "policy": {
    "levels": {
      "0": {
        "statsUserUplink": true,
        "statsUserDownlink": true
      }
    },
    "system": {
      "statsInboundUplink": false,
      "statsInboundDownlink": false,
      "statsOutboundUplink": true,
      "statsOutboundDownlink": true
    }
  },
  "inbounds": [
    {
      "listen": "127.0.0.1",
      "port": 10085,
      "protocol": "dokodemo-door",
      "settings": { "address": "127.0.0.1" },
      "tag": "api"
    },
    {
      "port": 443,
      "protocol": "vless",
      "tag": "main"
    }
  ],
  "outbounds": [
    { "protocol": "freedom", "tag": "direct" }
  ],
  "routing": {
    "rules": [
      { "type": "field", "inboundTag": ["api"], "outboundTag": "api" },
      { "type": "field", "outboundTag": "direct", "network": "tcp,udp" }
    ]
  }
}
"""


def run_script(config_path):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(config_path)],
        capture_output=True,
        text=True,
    )


def strip_jsonc(text):
    """Strip // # /* */ comments and trailing commas to get strict JSON."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i : j + 1])
            i = j + 1
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            nl = text.find("\n", i)
            i = n if nl == -1 else nl
        elif c == "#":
            nl = text.find("\n", i)
            i = n if nl == -1 else nl
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
        else:
            out.append(c)
            i += 1
    return re.sub(r",(\s*[\]}])", r"\1", "".join(out))


def load(path):
    return json.loads(strip_jsonc(Path(path).read_text()))


# ---- Idempotency on fully-configured input -------------------------------


def test_idempotent_on_fully_configured(tmp_path):
    """A config that already has every required piece — no changes."""
    target = tmp_path / "cfg.json"
    target.write_text(FULLY_CONFIGURED)
    before = target.read_text()

    result = run_script(target)

    assert result.returncode == EXIT_NO_CHANGES, result.stderr
    assert target.read_text() == before
    assert "already configured" in result.stdout
    assert list(tmp_path.glob("*.bak")) == []


def test_re_run_is_idempotent(tmp_path):
    """Two runs in a row: second is a no-op."""
    config = tmp_path / "cfg.json"
    config.write_text("{}")

    first = run_script(config)
    after_first = config.read_text()

    second = run_script(config)
    after_second = config.read_text()

    assert first.returncode == EXIT_CHANGES_APPLIED
    assert second.returncode == EXIT_NO_CHANGES
    assert after_first == after_second


# ---- Full bootstrap from an empty config ---------------------------------


def test_bare_object_adds_everything(tmp_path):
    """An empty {} grows all required stats components."""
    config = tmp_path / "cfg.json"
    config.write_text("{}\n")

    result = run_script(config)

    assert result.returncode == EXIT_CHANGES_APPLIED, result.stderr
    parsed = load(config)
    assert parsed["stats"] == {}
    assert parsed["api"]["tag"] == "api"
    assert set(parsed["api"]["services"]) >= {
        "StatsService",
        "LoggerService",
        "HandlerService",
    }
    zero = parsed["policy"]["levels"]["0"]
    assert zero["statsUserUplink"] is True
    assert zero["statsUserDownlink"] is True
    system = parsed["policy"]["system"]
    assert system["statsInboundUplink"] is False
    assert system["statsInboundDownlink"] is False
    assert system["statsOutboundUplink"] is True
    assert system["statsOutboundDownlink"] is True
    api_inbounds = [i for i in parsed["inbounds"] if i.get("tag") == "api"]
    assert len(api_inbounds) == 1
    assert api_inbounds[0]["protocol"] == "dokodemo-door"
    assert api_inbounds[0]["listen"] == "127.0.0.1"
    assert api_inbounds[0]["port"] == 10085
    first_rule = parsed["routing"]["rules"][0]
    assert first_rule["inboundTag"] == ["api"]
    assert first_rule["outboundTag"] == "api"


def test_output_for_strict_json_input_is_strict_json(tmp_path):
    """If the input has no comments/trailing commas, output is strict JSON."""
    config = tmp_path / "cfg.json"
    config.write_text("{}\n")
    run_script(config)
    json.loads(config.read_text())


# ---- JSONC features (comments, trailing commas, URLs) --------------------


def test_jsonc_comments_preserved(tmp_path):
    """// # and /* */ comments survive the edit."""
    config = tmp_path / "cfg.json"
    config.write_text(
        "// header line comment\n"
        "{\n"
        '  /* block comment */\n'
        '  "log": { "loglevel": "warning" },  // trailing line comment\n'
        '  # hash-style comment\n'
        '  "outbounds": [\n'
        '    { "protocol": "freedom", "tag": "direct" }\n'
        "  ]\n"
        "}\n"
    )

    result = run_script(config)
    assert result.returncode == EXIT_CHANGES_APPLIED, result.stderr

    text = config.read_text()
    assert "// header line comment" in text
    assert "/* block comment */" in text
    assert "// trailing line comment" in text
    assert "# hash-style comment" in text


def test_url_with_double_slash_in_string_preserved(tmp_path):
    """A `//` inside a string literal must not be treated as a comment."""
    config = tmp_path / "cfg.json"
    config.write_text('{"remarks": "see https://example.com/path"}')

    run_script(config)

    parsed = load(config)
    assert parsed["remarks"] == "see https://example.com/path"


def test_trailing_commas_in_input_do_not_break_parser(tmp_path):
    """JSONC-style trailing commas in input should parse cleanly."""
    config = tmp_path / "cfg.json"
    config.write_text(
        "{\n"
        '  "outbounds": [\n'
        '    { "tag": "direct", "protocol": "freedom", },\n'
        "  ],\n"
        "}\n"
    )

    result = run_script(config)
    assert result.returncode == EXIT_CHANGES_APPLIED, result.stderr
    parsed = load(config)
    assert parsed["api"]["tag"] == "api"


# ---- Selective insertion / duplicate avoidance ---------------------------


def test_partial_api_adds_services_only(tmp_path):
    """api.tag already set → don't duplicate; add only missing fields."""
    config = tmp_path / "cfg.json"
    config.write_text('{"api": {"tag": "api"}}')

    run_script(config)

    parsed = load(config)
    assert parsed["api"]["tag"] == "api"
    assert "StatsService" in parsed["api"]["services"]


def test_partial_policy_zero_adds_missing_flag(tmp_path):
    """Only the missing flag is added inside policy.levels.0."""
    config = tmp_path / "cfg.json"
    config.write_text(
        '{"policy": {"levels": {"0": {"statsUserUplink": true}}}}'
    )

    run_script(config)

    zero = load(config)["policy"]["levels"]["0"]
    assert zero["statsUserUplink"] is True
    assert zero["statsUserDownlink"] is True


def test_existing_api_inbound_not_duplicated(tmp_path):
    """An inbound already tagged "api" prevents adding another."""
    config = tmp_path / "cfg.json"
    config.write_text(
        '{"inbounds": ['
        '{"port": 10085, "protocol": "dokodemo-door", "tag": "api"}'
        "]}"
    )

    run_script(config)

    api_inbounds = [i for i in load(config)["inbounds"] if i.get("tag") == "api"]
    assert len(api_inbounds) == 1


def test_existing_api_routing_rule_not_duplicated(tmp_path):
    """An existing api routing rule prevents adding another."""
    config = tmp_path / "cfg.json"
    config.write_text(
        '{"routing": {"rules": ['
        '{"type": "field", "inboundTag": ["api"], "outboundTag": "api"}'
        "]}}"
    )

    run_script(config)

    rules = load(config)["routing"]["rules"]
    api_rules = [
        r
        for r in rules
        if r.get("inboundTag") == ["api"] and r.get("outboundTag") == "api"
    ]
    assert len(api_rules) == 1


def test_api_rule_prepended_to_existing_rules(tmp_path):
    """The api rule must be the FIRST routing rule."""
    config = tmp_path / "cfg.json"
    config.write_text(
        '{"routing": {"rules": ['
        '{"type": "field", "outboundTag": "direct", "network": "tcp,udp"}'
        "]}}"
    )

    run_script(config)

    rules = load(config)["routing"]["rules"]
    assert rules[0]["inboundTag"] == ["api"]
    assert rules[0]["outboundTag"] == "api"


def test_api_inbound_prepended_keeps_other_inbounds(tmp_path):
    """Existing inbounds remain after adding the api inbound."""
    config = tmp_path / "cfg.json"
    config.write_text(
        '{"inbounds": [{"port": 443, "protocol": "vless", "tag": "main"}]}'
    )

    run_script(config)

    parsed = load(config)
    tags = [i.get("tag") for i in parsed["inbounds"]]
    assert tags == ["api", "main"]


# ---- Backup & error handling ---------------------------------------------


def test_backup_created_only_when_changes_applied(tmp_path):
    """A timestamped backup is created iff changes were applied."""
    config = tmp_path / "cfg.json"
    config.write_text("{}")
    original = config.read_text()

    run_script(config)

    backups = sorted(tmp_path.glob("cfg.json.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text() == original


def test_no_backup_when_no_changes(tmp_path):
    """Idempotent run does not litter the directory with backups."""
    target = tmp_path / "cfg.json"
    target.write_text(FULLY_CONFIGURED)

    run_script(target)

    assert list(tmp_path.glob("cfg.json.*.bak")) == []


def test_missing_input_file_errors(tmp_path):
    """A non-existent config path exits non-zero with no backup created."""
    result = run_script(tmp_path / "nope.json")
    assert result.returncode != 0
    assert list(tmp_path.glob("*.bak")) == []
