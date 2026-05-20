# xray-stats

## Usage

`./install.sh`: Installs the scripts and sets up the environment.

`./install.sh <traffic-data-dir>`: Installs the scripts and sets up the environment with the specified traffic data directory.

## Scripts

`install.sh`: Sets up the environment and installs the necessary scripts.

`stats-collect`: Collects traffic statistics using the xray API and processes them.

`stats-query`: Summarizes the traffic data for each user on a specified date. If no date is provided, it defaults to the current date. It displays the downlink and uplink data in megabytes (MB) for each user.

## Configuration

The traffic data directory is stored in `/usr/local/etc/xray-stats/directory`. You can change this by re-running the `install.sh` script with a different directory.

## How it works

The `stats-collect` script collects and stores traffic data for each user:

1. Runs `xray api statsquery -reset` to get traffic stats.
1. Processes the output with `jq` using `stats-to-user-down-up.jq`.
1. Reads the traffic data directory path from `/usr/local/etc/xray-stats/directory`.
1. Appends downlink and uplink values to files named with the current date in the respective directories.

This organizes traffic data by user and date, with separate files for downlink and uplink data.

The file consists of multiple lines, each containing a traffic value in bytes. The script appends the traffic value to the file, creating a new file if it does not exist.

### Cron Job

The `install.sh` script installs a cron job from `xray-stats.cron`.

It runs the `stats-collect` script every 2 minutes, and runs `stats-shrink` to sum the traffic data for each user on the current date twice per hour (at `:29` and `:59`).

## Example directory structure

```
/var/local/xray-traffic/
├── user1/
│   ├── down/
│   │   └── 2024-01-01
│   └── up/
│       └── 2024-01-01
└── user2/
    ├── down/
    │   └── 2024-01-01
    └── up/
        └── 2024-01-01
```
