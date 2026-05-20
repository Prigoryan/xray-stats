#!/usr/bin/env bash

set -eo pipefail

DEFAULT_TRAFFIC_DATA_DIR=/var/local/xray-traffic
DEFAULT_API_SERVER=127.0.0.1:10085
DEFAULT_XRAY_CONFIG=/usr/local/etc/xray/config.json

if [ "$1" = '--help' ]; then
    echo "Usage: $0 [<traffic-data-dir> [<api-server> [<xray-config>]]]"
    echo "  <traffic-data-dir>  where per-user traffic counters are stored"
    echo "                      (defaults to $DEFAULT_TRAFFIC_DATA_DIR)"
    echo "  <api-server>        host:port of the xray stats API"
    echo "                      (defaults to $DEFAULT_API_SERVER)"
    echo "  <xray-config>       path to the xray config to patch"
    echo "                      (defaults to $DEFAULT_XRAY_CONFIG)"
    exit 0
fi

trafficDataDir=${1:-$DEFAULT_TRAFFIC_DATA_DIR}
apiServer=${2:-$DEFAULT_API_SERVER}
xrayConfig=${3:-$DEFAULT_XRAY_CONFIG}

here=$(dirname -- "$0")

"$here/enable-stats.sh" "$xrayConfig"

mkdir -p /usr/local/etc/xray-stats
echo "$trafficDataDir" > /usr/local/etc/xray-stats/directory
echo "$apiServer" > /usr/local/etc/xray-stats/server

{
    crontab -l 2>/dev/null | grep -v '/usr/local/bin/stats-' || true
    cat "$here/xray-stats.cron"
} | crontab -

cp "$here/stats-utils.sh" "$here/stats-query" "$here/stats-shrink" \
    "$here/stats-collect" "$here/stats-to-user-down-up.jq" \
    /usr/local/bin
