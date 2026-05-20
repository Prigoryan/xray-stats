#!/usr/bin/env bash

: "${XRAY_STATS_CONFIG_DIR:=/usr/local/etc/xray-stats}"

# shellcheck disable=SC2034 # Used in the sourcing scripts.
TRAFFIC_DIR=$(<"$XRAY_STATS_CONFIG_DIR/directory")
# shellcheck disable=SC2034 # Used in the sourcing scripts.
API_SERVER=$(<"$XRAY_STATS_CONFIG_DIR/server")

sum-num-file() {
    if [ "$#" -eq 0 ]; then
        echo 0
        return
    fi
    awk -v OFMT='%.f' '/^[0-9]+$/ {sum += $1} END {print sum + 0}' "$@" 2> /dev/null \
        || echo 0
}
