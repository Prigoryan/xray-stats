#!/usr/bin/env bash

set -eo pipefail

ff="$1"
if [ -z "$ff" ] || [ ! -f "$ff" ]; then
    echo "Usage: $0 <xray-config.json>" >&2
    exit 1
fi

rc=0
python3 "$(dirname "$0")/enable-stats.py" "$ff" || rc=$?

case "$rc" in
    0)
        systemctl restart xray
        ;;
    5)
        ;;
    *)
        exit "$rc"
        ;;
esac
