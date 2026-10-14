#!/usr/bin/python3
"""Free, local rclone bridge between iCloud Drive and Google My Drive.

No credentials are included in this source. OAuth credentials stay in rclone.conf.
"""
import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import plistlib
import shutil
import signal
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parent
RCLONE = BASE / "bin/rclone"
CONFIG = BASE / "settings.json"
AUTH = BASE / "rclone.conf"
LABEL = "local.steve.cloud-drive-sync"
PLIST = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
HEALTH = ".CloudDriveSyncHealth"
GIB = 1024 ** 3


def save_json(path, data):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n")
    os.chmod(temp, 0o600)
    temp.replace(path)


def rclone_args(*args):
    return [str(RCLONE), "--config", str(AUTH), *map(str, args)]


def bisync_args(local, remote, workdir, backup1, backup2, filters,
                initialize=False, dry_run=False):
    args = rclone_args(
        "bisync", local, remote,
        "--workdir", workdir,
        "--filters-file", filters,
        "--backup-dir1", backup1,
        "--backup-dir2", backup2,
        "--check-access", "--check-filename", HEALTH,
        "--max-delete", "10",
        "--conflict-resolve", "none", "--conflict-loser", "num",
        "--suffix-keep-extension",
        "--compare", "size,modtime,checksum", "--slow-hash-sync-only",
        "--create-empty-src-dirs", "--links", "--fix-case",
        "--drive-skip-gdocs", "--drive-skip-shortcuts",
        "--disable", "ListR",
        "--resilient", "--recover", "--max-lock", "5m",
        "--checkers", "4", "--transfers", "2", "--tpslimit", "5",
        "--contimeout", "15s", "--timeout", "2m",
        "--retries", "3", "--retries-sleep", "10s",
        "--stats", "1m", "--stats-one-line", "--log-level", "INFO",
    )
    if initialize:
        args += ["--resync-mode", "newer"]
    if dry_run:
        args += ["--dry-run"]
    return args


def notify(message):
    # Notifications are optional; the durable status file is always updated.
    print(message, flush=True)


def execute(settings, initialize=False, dry_run=False):
    if not initialize and not settings.get("initialized"):
        raise RuntimeError("Initial merge has not completed. Automatic syncing is disabled.")
    local = Path(settings["local"])
    if not local.is_dir() or not (local / HEALTH).is_file():
        raise RuntimeError("iCloud Drive or its health marker is unavailable; no files changed.")
    if shutil.disk_usage(local).free < 4 * GIB:
        raise RuntimeError("Less than 4 GiB free on the Mac; no sync started.")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    name = settings["name"]
    filters = BASE / settings["filters"]
    log = BASE / "logs" / (stamp + "-" + name + ("-preview" if dry_run else "-sync") + ".log")
    backup1 = BASE / "backups/icloud" / name / stamp
    backup2 = settings["remote"].rstrip("/") + ("" if settings["remote"].endswith(":") else "/") + ".CloudDriveSyncBackups/" + stamp
    command = bisync_args(local, settings["remote"], BASE / "state/bisync" / name,
                          backup1, backup2, filters, initialize, dry_run)
    state = {"state": "previewing" if dry_run else "syncing", "started": dt.datetime.now().astimezone().isoformat(),
             "log": str(log), "initial_merge": initialize, "job": name}
    save_json(BASE / "status.json", state)
    print("Log:", log, flush=True)
    with log.open("w") as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
        low_space = False
        def stop(_signum, _frame):
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
        old_int = signal.signal(signal.SIGINT, stop)
        old_term = signal.signal(signal.SIGTERM, stop)
        try:
            while process.poll() is None:
                if not low_space and shutil.disk_usage(local).free < 2 * GIB:
                    low_space = True
                    process.send_signal(signal.SIGINT)
                time.sleep(2)
        finally:
            signal.signal(signal.SIGINT, old_int)
            signal.signal(signal.SIGTERM, old_term)
    code = process.returncode
    state.update(state="success" if code == 0 else "needs_attention", exit_code=code,
                 finished=dt.datetime.now().astimezone().isoformat(), low_disk_space=low_space)
    save_json(BASE / "status.json", state)
    if code:
        raise RuntimeError("Sync stopped. See " + str(log) + ". It will never automatically run --resync.")
    if initialize and not dry_run:
        settings["initialized"] = True
    if initialize and dry_run:
        save_json(BASE / "state" / ("preview-" + name + ".json"), {"local": str(local), "remote": settings["remote"],
                  "filters": filters.read_text(), "completed": time.time(), "log": str(log)})
    # Retain the latest 200 logs. Recovery copies are never automatically removed.
    logs = sorted((BASE / "logs").glob("*.log"))
    for old_log in logs[:-200]:
        old_log.unlink()
    notify("Preview completed." if dry_run else "Sync completed.")


def install_schedule():
    data = {"Label": LABEL,
            "ProgramArguments": [sys.executable, str(BASE / "sync.py"), "run"],
            "StartInterval": 300, "RunAtLoad": True,
            "WorkingDirectory": str(BASE), "ProcessType": "Background",
            "EnvironmentVariables": {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
            "StandardOutPath": str(BASE / "logs/scheduler.stdout.log"),
            "StandardErrorPath": str(BASE / "logs/scheduler.stderr.log"),
            "ExitTimeOut": 120, "ThrottleInterval": 60}
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(plistlib.dumps(data))
    return PLIST


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["preview", "initialize", "run", "status", "enable", "disable", "prepare-health"])
    action = parser.parse_args().action
    settings = json.loads(CONFIG.read_text())
    if action == "status":
        status = json.loads((BASE / "status.json").read_text()) if (BASE / "status.json").exists() else {"state": "not_started"}
        schedule = subprocess.run(["/bin/launchctl", "print", "gui/" + str(os.getuid()) + "/" + LABEL], capture_output=True)
        print(json.dumps({"jobs": settings["jobs"],
              "initialized": settings.get("initialized", False), "schedule_loaded": schedule.returncode == 0,
              "free_gib": round(shutil.disk_usage(BASE).free / GIB, 1), "last_run": status}, indent=2))
        return
    if action == "disable":
        subprocess.run(["/bin/launchctl", "bootout", "gui/" + str(os.getuid()) + "/" + LABEL], check=False)
        print("Automatic syncing is disabled. Existing files are unchanged.")
        return
    if action == "enable":
        if not settings.get("initialized"):
            raise RuntimeError("Finish the initial merge before enabling the schedule.")
        plist = install_schedule()
        subprocess.run(["/bin/launchctl", "bootstrap", "gui/" + str(os.getuid()), str(plist)], check=True)
        print("Automatic syncing is enabled every five minutes and at login.")
        return
    with (BASE / "state/runner.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another sync is already running; skipping this invocation.")
            return
        if action == "prepare-health":
            for job in settings["jobs"]:
                marker = Path(job["local"]) / HEALTH
                if not marker.exists():
                    marker.write_text("Cloud Drive Sync health marker. Keep this file in both drives.\n")
                remote = job["remote"] + ("" if job["remote"].endswith((":", "/")) else "/") + HEALTH
                subprocess.run(rclone_args("copyto", marker, remote, "--immutable"), check=True)
            print("Health markers prepared.")
            return
        if action == "initialize":
            if settings.get("initialized"):
                raise RuntimeError("Already initialized. Use run; reinitialization needs a reviewed recovery plan.")
            for job in settings["jobs"]:
                preview = json.loads((BASE / "state" / ("preview-" + job["name"] + ".json")).read_text())
                if preview["local"] != job["local"] or preview["remote"] != job["remote"] or preview["filters"] != (BASE / job["filters"]).read_text() or time.time() - preview["completed"] > 86400:
                    raise RuntimeError("Run a new preview before the initial merge.")
        for job in settings["jobs"]:
            execute(job, initialize=action in ["preview", "initialize"] and not job.get("initialized"), dry_run=action == "preview")
            if action != "preview":
                settings["initialized"] = all(j.get("initialized") for j in settings["jobs"])
                save_json(CONFIG, settings)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
