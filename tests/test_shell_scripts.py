"""End-to-end tests for the shell scripts.

Each test sets up an isolated XRAY_STATS_CONFIG_DIR pointing at a tmp_path
fixture, then invokes the script under test via subprocess. This mirrors
the production code path (file-backed config + script entry point) without
touching /usr/local/etc.
"""

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
STATS_UTILS = REPO_ROOT / "stats-utils.sh"
STATS_QUERY = REPO_ROOT / "stats-query"
STATS_SHRINK = REPO_ROOT / "stats-shrink"
STATS_COLLECT = REPO_ROOT / "stats-collect"
INSTALL = REPO_ROOT / "install.sh"


def make_config(tmp_path, traffic_dir=None, api_server="127.0.0.1:10085"):
    """Build an isolated XRAY_STATS_CONFIG_DIR fixture."""
    cfg = tmp_path / "etc"
    cfg.mkdir()
    if traffic_dir is None:
        traffic_dir = tmp_path / "traffic"
        traffic_dir.mkdir()
    (cfg / "directory").write_text(f"{traffic_dir}\n")
    (cfg / "server").write_text(f"{api_server}\n")
    return cfg, Path(traffic_dir)


def script_env(config_dir):
    env = os.environ.copy()
    env["XRAY_STATS_CONFIG_DIR"] = str(config_dir)
    return env


def run(script, *args, env=None, cwd=None):
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        timeout=10,
    )


# ---- install.sh ----------------------------------------------------------


def test_install_help_exits_zero():
    """--help is a successful invocation, not an error."""
    result = run(INSTALL, "--help")
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "<traffic-data-dir>" in result.stdout
    assert "<api-server>" in result.stdout
    assert "<xray-config>" in result.stdout


# ---- sum-num-file (stats-utils.sh) ---------------------------------------


def call_sum(tmp_path, *files):
    """Source stats-utils.sh and invoke sum-num-file with the given args."""
    cfg, _ = make_config(tmp_path)
    quoted = " ".join(f'"{f}"' for f in files)
    script = f'source "{STATS_UTILS}"; sum-num-file {quoted}'
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=script_env(cfg),
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_sum_num_file_no_args_returns_zero(tmp_path):
    """Zero args must NOT hang on stdin; must print 0."""
    assert call_sum(tmp_path) == "0"


def test_sum_num_file_missing_file_returns_zero(tmp_path):
    """Nonexistent paths sum to 0 (awk failure is swallowed)."""
    assert call_sum(tmp_path, tmp_path / "nope") == "0"


def test_sum_num_file_sums_integers(tmp_path):
    f = tmp_path / "nums"
    f.write_text("10\n20\n30\n")
    assert call_sum(tmp_path, f) == "60"


def test_sum_num_file_skips_non_numeric_lines(tmp_path):
    f = tmp_path / "mixed"
    f.write_text("10\nbanana\n20\n\n0xff\n")
    assert call_sum(tmp_path, f) == "30"


def test_sum_num_file_all_non_numeric_returns_zero(tmp_path):
    """A file with no numeric lines still prints 0, not empty string."""
    f = tmp_path / "garbage"
    f.write_text("abc\ndef\n")
    assert call_sum(tmp_path, f) == "0"


def test_sum_num_file_handles_large_sum(tmp_path):
    """Sums larger than 2^32 don't get formatted as scientific notation."""
    f = tmp_path / "big"
    # 5 lines of ~200GB each → 10^12-ish total
    f.write_text("\n".join(["200000000000"] * 5) + "\n")
    assert call_sum(tmp_path, f) == "1000000000000"


# ---- stats-query ---------------------------------------------------------


def test_stats_query_rejects_bad_month(tmp_path):
    """Month 13 is not a valid month."""
    cfg, _ = make_config(tmp_path)
    result = run(STATS_QUERY, "2024-13", env=script_env(cfg))
    assert result.returncode != 0


def test_stats_query_rejects_month_zero(tmp_path):
    cfg, _ = make_config(tmp_path)
    result = run(STATS_QUERY, "2024-00", env=script_env(cfg))
    assert result.returncode != 0


def test_stats_query_rejects_invalid_day(tmp_path):
    """Day 32 is not a valid day."""
    cfg, _ = make_config(tmp_path)
    result = run(STATS_QUERY, "2024-02-32", env=script_env(cfg))
    assert result.returncode != 0


def test_stats_query_rejects_day_zero(tmp_path):
    cfg, _ = make_config(tmp_path)
    result = run(STATS_QUERY, "2024-02-00", env=script_env(cfg))
    assert result.returncode != 0


def test_stats_query_rejects_garbage(tmp_path):
    cfg, _ = make_config(tmp_path)
    result = run(STATS_QUERY, "not-a-date", env=script_env(cfg))
    assert result.returncode != 0


def test_stats_query_accepts_valid_date(tmp_path):
    cfg, _ = make_config(tmp_path)
    result = run(STATS_QUERY, "--plain", "2024-02-29", env=script_env(cfg))
    assert result.returncode == 0


def test_stats_query_accepts_valid_month(tmp_path):
    cfg, _ = make_config(tmp_path)
    result = run(STATS_QUERY, "--plain", "2024-12", env=script_env(cfg))
    assert result.returncode == 0


def test_stats_query_no_users_silent(tmp_path):
    """Empty TRAFFIC_DIR + valid date → no output, exit 0 (nullglob)."""
    cfg, _ = make_config(tmp_path)
    result = run(STATS_QUERY, "--plain", "2024-01-01", env=script_env(cfg))
    assert result.returncode == 0
    assert result.stdout == ""


def test_stats_query_sums_daily(tmp_path):
    cfg, traffic = make_config(tmp_path)
    (traffic / "alice/down").mkdir(parents=True)
    (traffic / "alice/up").mkdir(parents=True)
    (traffic / "alice/down/2024-01-01").write_text("1048576\n1048576\n")  # 2 MiB
    (traffic / "alice/up/2024-01-01").write_text("524288\n")              # 0.5 MiB → 0 MB int
    result = run(STATS_QUERY, "--plain", "2024-01-01", env=script_env(cfg))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "alice 2097152 524288"


def test_stats_query_sums_monthly(tmp_path):
    cfg, traffic = make_config(tmp_path)
    (traffic / "bob/down").mkdir(parents=True)
    (traffic / "bob/up").mkdir(parents=True)
    (traffic / "bob/down/2024-01-01").write_text("100\n")
    (traffic / "bob/down/2024-01-15").write_text("200\n")
    (traffic / "bob/down/2024-02-01").write_text("999\n")  # different month
    (traffic / "bob/up/2024-01-10").write_text("50\n")
    result = run(STATS_QUERY, "--plain", "2024-01", env=script_env(cfg))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "bob 300 50"


def test_stats_query_user_glob(tmp_path):
    """The user-glob argument filters which user dirs are summed."""
    cfg, traffic = make_config(tmp_path)
    for u in ("alice", "bob", "carol"):
        (traffic / u / "down").mkdir(parents=True)
        (traffic / u / "up").mkdir(parents=True)
        (traffic / u / "down/2024-01-01").write_text("1\n")
        (traffic / u / "up/2024-01-01").write_text("1\n")
    result = run(STATS_QUERY, "--plain", "2024-01-01", "a*", env=script_env(cfg))
    assert result.returncode == 0, result.stderr
    users = [line.split()[0] for line in result.stdout.strip().splitlines()]
    assert users == ["alice"]


# ---- stats-shrink --------------------------------------------------------


def test_stats_shrink_compacts_file(tmp_path):
    cfg, traffic = make_config(tmp_path)
    (traffic / "alice/down").mkdir(parents=True)
    (traffic / "alice/up").mkdir(parents=True)
    down = traffic / "alice/down/2024-01-01"
    up = traffic / "alice/up/2024-01-01"
    down.write_text("10\n20\n30\n")
    up.write_text("5\n5\n")
    result = run(STATS_SHRINK, "2024-01-01", env=script_env(cfg))
    assert result.returncode == 0, result.stderr
    assert down.read_text().strip() == "60"
    assert up.read_text().strip() == "10"


def test_stats_shrink_no_files_noop(tmp_path):
    """No matching files → quiet exit 0, no errors."""
    cfg, _ = make_config(tmp_path)
    result = run(STATS_SHRINK, "2024-01-01", env=script_env(cfg))
    assert result.returncode == 0, result.stderr


# ---- stats-collect -------------------------------------------------------


def make_xray_shim(bin_dir, stat_entries):
    """Write a fake `xray` that prints the given stat entries as JSON."""
    bin_dir.mkdir(exist_ok=True)
    items = ",\n    ".join(
        f'{{"name":"{name}","value":"{value}"}}'
        for name, value in stat_entries
    )
    shim = bin_dir / "xray"
    shim.write_text(
        "#!/bin/sh\n"
        "cat <<'EOF'\n"
        f'{{"stat":[\n    {items}\n]}}\n'
        "EOF\n"
    )
    shim.chmod(0o755)
    return shim


def test_stats_collect_writes_per_user_files(tmp_path):
    cfg, traffic = make_config(tmp_path)
    bin_dir = tmp_path / "bin"
    make_xray_shim(bin_dir, [
        ("user>>>alice>>>traffic>>>downlink", "100"),
        ("user>>>alice>>>traffic>>>uplink", "50"),
    ])
    env = script_env(cfg)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    result = run(STATS_COLLECT, env=env)
    assert result.returncode == 0, result.stderr

    today = subprocess.run(
        ["date", "+%F"], capture_output=True, text=True
    ).stdout.strip()
    assert (traffic / "alice/down" / today).read_text().strip() == "100"
    assert (traffic / "alice/up" / today).read_text().strip() == "50"


def test_stats_collect_rejects_path_traversal_user(tmp_path):
    """A user name containing '/' must not escape TRAFFIC_DIR."""
    cfg, traffic = make_config(tmp_path)
    bin_dir = tmp_path / "bin"
    make_xray_shim(bin_dir, [
        ("user>>>../escape>>>traffic>>>downlink", "1000"),
        ("user>>>../escape>>>traffic>>>uplink", "2000"),
        ("user>>>alice>>>traffic>>>downlink", "100"),
        ("user>>>alice>>>traffic>>>uplink", "50"),
    ])
    env = script_env(cfg)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    result = run(STATS_COLLECT, env=env)
    assert result.returncode == 0, result.stderr

    # The legit user got recorded.
    today = subprocess.run(
        ["date", "+%F"], capture_output=True, text=True
    ).stdout.strip()
    assert (traffic / "alice/down" / today).exists()

    # The malicious user did NOT escape the traffic dir.
    assert not (tmp_path / "escape").exists()
    assert not (traffic / ".." / "escape").exists()
    assert not list(tmp_path.rglob("escape"))
    assert "suspicious" in result.stderr


def test_stats_collect_skips_dotdot_user(tmp_path):
    cfg, traffic = make_config(tmp_path)
    bin_dir = tmp_path / "bin"
    make_xray_shim(bin_dir, [
        ("user>>>..>>>traffic>>>downlink", "1000"),
        ("user>>>..>>>traffic>>>uplink", "2000"),
    ])
    env = script_env(cfg)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"

    result = run(STATS_COLLECT, env=env)
    assert result.returncode == 0, result.stderr
    # No siblings of TRAFFIC_DIR should have been created.
    assert list(traffic.iterdir()) == []


def test_stats_shrink_preserves_total_across_runs(tmp_path):
    """Shrinking is idempotent: re-running yields the same value."""
    cfg, traffic = make_config(tmp_path)
    (traffic / "alice/down").mkdir(parents=True)
    (traffic / "alice/up").mkdir(parents=True)
    f = traffic / "alice/down/2024-01-01"
    f.write_text("100\n200\n")
    (traffic / "alice/up/2024-01-01").write_text("0\n")
    run(STATS_SHRINK, "2024-01-01", env=script_env(cfg))
    first = f.read_text()
    run(STATS_SHRINK, "2024-01-01", env=script_env(cfg))
    assert f.read_text() == first
    assert first.strip() == "300"
