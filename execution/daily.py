#!/usr/bin/env python3
"""The daily loop: pull Instagram numbers, sync the ledger, refresh the mirror.

Designed to run on a schedule (Task Scheduler on Windows, cron/launchd on
Mac/Linux). If the pull fails, the sync still runs on the latest existing
snapshot, because syncing yesterday's numbers beats syncing nothing. Every
run appends one line to analytics/sync_log.txt even when nothing changed, so
silence in the log means the schedule broke rather than "no news".

Usage:
    python execution/daily.py
"""

import datetime as dt
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "analytics" / "sync_log.txt"


def run(script):
    result = subprocess.run([sys.executable, str(ROOT / "execution" / script)],
                            capture_output=True, text=True, cwd=ROOT)
    output = (result.stdout or "") + (result.stderr or "")
    print(f"--- {script} (exit {result.returncode}) ---")
    print(output.strip())
    return result.returncode == 0, output


def main():
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    pull_ok, _ = run("ig_pull.py")
    sync_ok, sync_out = run("sync.py")
    export_ok, _ = run("export.py")

    unlinked = "?"
    for line in sync_out.splitlines():
        if "posts are unlinked" in line:
            unlinked = line.split()[1]
        if "100 percent" in line:
            unlinked = "0"

    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{stamp} pull={'ok' if pull_ok else 'FAIL'} "
                f"sync={'ok' if sync_ok else 'FAIL'} "
                f"export={'ok' if export_ok else 'FAIL'} "
                f"unlinked={unlinked}\n")
    print(f"\nLogged -> {LOG}")
    sys.exit(0 if sync_ok else 1)


if __name__ == "__main__":
    main()
