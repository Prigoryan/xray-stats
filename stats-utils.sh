#!/usr/bin/env bash

# shellcheck disable=SC2034 # Used in the sourcing scripts.
TRAFFIC_DIR=$(</usr/local/etc/xray-stats/directory)

sum-num-file() {
    awk -v OFMT='%.f' '/^[0-9]+$/ {sum += $1} END {print sum}' "$@" 2> /dev/null \
        || echo 0
}
