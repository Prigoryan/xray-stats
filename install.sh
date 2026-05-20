#!/usr/bin/env bash

set -eo pipefail

DEFAULT_TRAFFIC_DATA_DIR=/var/local/xray-traffic
DEFAULT_API_SERVER=127.0.0.1:10085

if [ "$1" == '--help' ]; then
    echo "Usage: $0 [<traffic-data-dir> [<api-server>]]"
    echo "  <traffic-data-dir>  where per-user traffic counters are stored"
    echo "                      (defaults to $DEFAULT_TRAFFIC_DATA_DIR)"
    echo "  <api-server>        host:port of the xray stats API"
    echo "                      (defaults to $DEFAULT_API_SERVER)"
    exit 1
fi

trafficDataDir=${1:-$DEFAULT_TRAFFIC_DATA_DIR}
apiServer=${2:-$DEFAULT_API_SERVER}

./enable-stats.sh /usr/local/etc/xray/config.json

mkdir -p /usr/local/etc/xray-stats
echo "$trafficDataDir" > /usr/local/etc/xray-stats/directory
echo "$apiServer" > /usr/local/etc/xray-stats/server

{
    crontab -l 2>/dev/null | grep -v '/usr/local/bin/stats-' || true
    cat xray-stats.cron
} | crontab -

cp stats-utils.sh stats-query stats-shrink stats-collect stats-to-user-down-up.jq \
    /usr/local/bin
