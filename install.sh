#!/usr/bin/env bash

set -eo pipefail

DEFAULT_TRAFFIC_DATA_DIR=/var/local/xray-traffic

trafficDataDir=$1
if [ "$trafficDataDir" == '--help' ]; then
    echo "Usage: $0"
    echo "Usage: $0 <traffic-data-dir>"
    echo "(defaults to $DEFAULT_TRAFFIC_DATA_DIR)"
    exit 1
fi

if [ -z "$trafficDataDir" ]; then
    trafficDataDir=$DEFAULT_TRAFFIC_DATA_DIR
fi

./enable-stats.sh /usr/local/etc/xray/config.json

mkdir -p /usr/local/etc/xray-stats
echo "$trafficDataDir" > /usr/local/etc/xray-stats/directory

{
    crontab -l 2>/dev/null | grep -v '/usr/local/bin/stats-' || true
    cat xray-stats.cron
} | crontab -

cp stats-utils.sh stats-query stats-shrink stats-collect stats-to-user-down-up.jq \
    /usr/local/bin
