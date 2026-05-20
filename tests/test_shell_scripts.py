"""End-to-end tests for the shell scripts via XRAY_STATS_CONFIG_DIR."""

import datetime
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
STATS_UTILS = REPO_ROOT / "stats-utils.sh"
STATS_QUERY = REPO_ROOT / "stats-query"
STATS_SHRINK = REPO_ROOT / "stats-shrink"
STATS_COLLECT = REPO_ROOT / "stats-collect"
INSTALL = REPO_ROOT / "install.sh"


def make_config(tmp_path, traffic_dir=None, api_server="127.0.0.1:10085"):
    cfg = tmp_path / "etc"
    cfg.mkdir()
    if traffic_dir is None:
        traffic_dir = tmp_path / "traffic"
        traffic_dir.mkdir()
    (cfg / "directory").write_text(f"{traffic_dir}\n")
    (cfg / "server").write_text(f"{api_server}\n")
    return cfg, Path(traffic_dir)


def script_env(config_dir, bin_dir=None):
    env = os.environ.copy()
    env["XRAY_STATS_CONFIG_DIR"] = str(config_dir)
    if bin_dir is not None:
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
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
    f.write_text("\n".join(["200000000000"] * 5) + "\n")
    assert call_sum(tmp_path, f) == "1000000000000"


# ---- stats-query ---------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    ["2024-13", "2024-00", "2024-02-32", "2024-02-00", "not-a-date"],
)
def test_stats_query_rejects_invalid_date(tmp_path, bad):
    cfg, _ = make_config(tmp_path)
    result = run(STATS_QUERY, bad, env=script_env(cfg))
    assert result.returncode != 0


@pytest.mark.parametrize("good", ["2024-02-29", "2024-12"])
def test_stats_query_accepts_valid_date(tmp_path, good):
    cfg, _ = make_config(tmp_path)
    result = run(STATS_QUERY, "--plain", good, env=script_env(cfg))
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
    (traffic / "alice/down/2024-01-01").write_text("1048576\n1048576\n")
    (traffic / "alice/up/2024-01-01").write_text("524288\n")
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


def test_stats_shrink_preserves_total_across_runs(tmp_path):
    """Idempotent: re-running yields the same value."""
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

    result = run(STATS_COLLECT, env=script_env(cfg, bin_dir=bin_dir))
    assert result.returncode == 0, result.stderr

    today = datetime.date.today().isoformat()
    assert (traffic / "alice/down" / today).read_text().strip() == "100"
    assert (traffic / "alice/up" / today).read_text().strip() == "50"


@pytest.mark.parametrize("bad_user", ["../escape", "..", ".", "a/b"])
def test_stats_collect_rejects_unsafe_user(tmp_path, bad_user):
    """A suspicious user name must not write outside TRAFFIC_DIR; a legit
    entry alongside must still be recorded."""
    cfg, traffic = make_config(tmp_path)
    bin_dir = tmp_path / "bin"
    make_xray_shim(bin_dir, [
        (f"user>>>{bad_user}>>>traffic>>>downlink", "1000"),
        (f"user>>>{bad_user}>>>traffic>>>uplink", "2000"),
        ("user>>>alice>>>traffic>>>downlink", "100"),
        ("user>>>alice>>>traffic>>>uplink", "50"),
    ])

    result = run(STATS_COLLECT, env=script_env(cfg, bin_dir=bin_dir))
    assert result.returncode == 0, result.stderr

    today = datetime.date.today().isoformat()
    assert (traffic / "alice/down" / today).read_text().strip() == "100"
    assert (traffic / "alice/up" / today).read_text().strip() == "50"

    # Nothing named "escape" anywhere, and traffic_dir has only "alice".
    assert not list(tmp_path.rglob("escape"))
    assert [p.name for p in traffic.iterdir()] == ["alice"]
    assert "suspicious" in result.stderr
