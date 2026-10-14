#!/usr/bin/python3
"""Free cloud-file bridge: automatic operations only copy, never delete.
Missing files return from the other side; replaced versions stay in both clouds.
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
RCLONE = BASE / 'bin/rclone'
AUTH = BASE / 'rclone.conf'
CONFIG = BASE / 'settings.json'
APP = Path.home() / 'Applications/Cloud Drive Sync.app/Contents/MacOS/CloudDriveSync'
LABEL = 'local.steve.cloud-drive-sync'
PLIST = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
INITIAL_LABEL = LABEL + '-initial'
INITIAL_PLIST = PLIST.with_name(INITIAL_LABEL + '.plist')
PAUSED = BASE / 'PAUSED'
HEALTH = '.CloudDriveSyncHealth'
HISTORY = '.CloudDriveSyncBackups'
GIB = 1024 ** 3


def save_json(path, data):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, indent=2) + '\n')
    os.chmod(temp, 0o600)
    temp.replace(path)


def rclone_args(*args):
    return [str(RCLONE), '--config', str(AUTH), *map(str, args)]


def remote_join(root, suffix):
    return root + ('' if root.endswith((':', '/')) else '/') + suffix


def copy_args(source, destination, backup=None, filters=None, dry_run=False, history=False):
    # Never use sync, bisync, delete, purge, move, or automatic history cleanup.
    args = rclone_args('copy', source, destination,
        '--create-empty-src-dirs', '--links', '--ignore-case-sync',
        '--drive-skip-gdocs', '--drive-skip-shortcuts',
        '--checkers', '4', '--transfers', '2', '--tpslimit', '5',
        '--contimeout', '15s', '--timeout', '2m',
        '--retries', '3', '--retries-sleep', '10s',
        '--stats', '1m', '--stats-one-line', '--log-level', 'INFO')
    if history:
        args += ['--ignore-existing']
    else:
        if backup is None or filters is None:
            raise RuntimeError('Every normal copy requires recovery storage and explicit filters.')
        args += ['--update', '--backup-dir', str(backup), '--filter-from', str(filters)]
    if dry_run:
        args += ['--dry-run']
    return args


def run_process(command, output):
    if shutil.disk_usage(BASE).free < 4 * GIB:
        raise RuntimeError('Less than 4 GiB free. Copy stopped; no cleanup or deletions will be attempted.')
    process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
    low_space = False
    def stop(_signum, _frame):
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
    old_int = signal.signal(signal.SIGINT, stop)
    old_term = signal.signal(signal.SIGTERM, stop)
    try:
        while process.poll() is None:
            if not low_space and shutil.disk_usage(BASE).free < 2 * GIB:
                low_space = True
                process.send_signal(signal.SIGINT)
            time.sleep(2)
    finally:
        signal.signal(signal.SIGINT, old_int)
        signal.signal(signal.SIGTERM, old_term)
    if process.returncode:
        raise RuntimeError('Copy stopped with exit code ' + str(process.returncode))


def execute(job, initial=False, dry_run=False):
    local = Path(job['local'])
    if not local.is_dir() or not (local / HEALTH).is_file():
        raise RuntimeError('Sync folder or health marker unavailable. No changes attempted.')
    check = subprocess.run(rclone_args('cat', remote_join(job['remote'], HEALTH),
        '--contimeout', '15s', '--timeout', '30s', '--retries', '1'), capture_output=True)
    if check.returncode or not check.stdout:
        raise RuntimeError('Google Drive health marker unavailable. No changes attempted.')
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    log = BASE / 'logs' / (stamp + '-' + job['name'] + ('-preview' if dry_run else '-copy') + '.log')
    local_history = local / HISTORY
    remote_history = remote_join(job['remote'], HISTORY)
    filters = BASE / job['filters']
    operations = [
        ('Google to iCloud', copy_args(job['remote'], local, local_history / 'icloud' / stamp, filters, dry_run)),
        ('iCloud to Google', copy_args(local, job['remote'], remote_join(remote_history, 'google/' + stamp), filters, dry_run)),
    ]
    if not dry_run:
        local_history.mkdir(exist_ok=True)
        subprocess.run(rclone_args('mkdir', remote_history, '--contimeout', '15s', '--timeout', '1m'), check=True)
        operations += [
            ('Preserve iCloud recovery copies in Google', copy_args(local_history, remote_history, history=True)),
            ('Preserve Google recovery copies in iCloud', copy_args(remote_history, local_history, history=True)),
        ]
    state = {'state': 'previewing' if dry_run else 'copying', 'job': job['name'],
             'initial_merge': initial, 'delete_policy': 'never', 'log': str(log),
             'started': dt.datetime.now().astimezone().isoformat()}
    save_json(BASE / 'status.json', state)
    print('Log:', log, flush=True)
    try:
        with log.open('w') as output:
            for description, command in operations:
                state['operation'] = description
                save_json(BASE / 'status.json', state)
                output.write('\n' + description + '\n'); output.flush()
                run_process(command, output)
        state.update(state='success', finished=dt.datetime.now().astimezone().isoformat())
        if not dry_run:
            job['initialized'] = True
        print('Preview completed.' if dry_run else 'Copy completed; no deletions propagated.', flush=True)
    except Exception as error:
        state.update(state='needs_attention', error=str(error), finished=dt.datetime.now().astimezone().isoformat())
        raise
    finally:
        save_json(BASE / 'status.json', state)


def install_schedule():
    data = {'Label': LABEL, 'ProgramArguments': [str(APP), 'run'],
            'StartInterval': 300, 'RunAtLoad': True, 'WorkingDirectory': str(BASE),
            'ProcessType': 'Background', 'ExitTimeOut': 120, 'ThrottleInterval': 60,
            'EnvironmentVariables': {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin'},
            'StandardOutPath': str(BASE / 'logs/scheduler.stdout.log'),
            'StandardErrorPath': str(BASE / 'logs/scheduler.stderr.log')}
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(plistlib.dumps(data))
    return PLIST


def install_initial_schedule():
    data = {'Label': INITIAL_LABEL,
            'ProgramArguments': ['/usr/bin/python3', str(BASE / 'initial-copy.py')],
            'RunAtLoad': True, 'KeepAlive': {'SuccessfulExit': False},
            'ThrottleInterval': 300, 'ExitTimeOut': 120,
            'WorkingDirectory': str(BASE), 'ProcessType': 'Background',
            'StandardOutPath': str(BASE / 'logs/initial.stdout.log'),
            'StandardErrorPath': str(BASE / 'logs/initial.stderr.log')}
    INITIAL_PLIST.write_bytes(plistlib.dumps(data))
    return INITIAL_PLIST


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['preview', 'initialize', 'run', 'status', 'enable', 'disable', 'prepare-health'])
    action = parser.parse_args().action
    settings = json.loads(CONFIG.read_text())
    if settings.get('delete_policy') != 'never':
        raise RuntimeError('Automatic deletion is prohibited. Required policy: delete_policy=never.')
    if action == 'status':
        status = json.loads((BASE / 'status.json').read_text()) if (BASE / 'status.json').exists() else {'state': 'not_started'}
        schedule = subprocess.run(['/bin/launchctl', 'print', 'gui/' + str(os.getuid()) + '/' + LABEL], capture_output=True)
        initial = subprocess.run(['/bin/launchctl', 'print', 'gui/' + str(os.getuid()) + '/' + INITIAL_LABEL], capture_output=True)
        print(json.dumps({'jobs': settings['jobs'], 'delete_policy': 'never',
              'initialized': settings.get('initialized', False), 'schedule_loaded': schedule.returncode == 0,
              'initial_worker_loaded': initial.returncode == 0, 'paused': PAUSED.exists(),
              'free_gib': round(shutil.disk_usage(BASE).free / GIB, 1), 'last_run': status}, indent=2))
        return
    if action == 'disable':
        PAUSED.write_text('Paused by the user. Resume Automatic Sync.command re-enables copying.\n')
        for label in [LABEL, INITIAL_LABEL]:
            service = 'gui/' + str(os.getuid()) + '/' + label
            subprocess.run(['/bin/launchctl', 'disable', service], capture_output=True)
            subprocess.run(['/bin/launchctl', 'bootout', service], capture_output=True)
        print('Automatic copying disabled. Existing cloud files are unchanged.')
        return
    if action == 'enable':
        PAUSED.unlink(missing_ok=True)
        for label in [LABEL, INITIAL_LABEL]:
            subprocess.run(['/bin/launchctl', 'enable', 'gui/' + str(os.getuid()) + '/' + label], check=True)
        label = LABEL if settings.get('initialized') else INITIAL_LABEL
        loaded = subprocess.run(['/bin/launchctl', 'print', 'gui/' + str(os.getuid()) + '/' + label], capture_output=True)
        if loaded.returncode:
            plist = install_schedule() if settings.get('initialized') else install_initial_schedule()
            subprocess.run(['/bin/launchctl', 'bootstrap', 'gui/' + str(os.getuid()), str(plist)], check=True)
        print('Automatic copying enabled every five minutes.' if settings.get('initialized') else 'Initial copying enabled; five-minute copying will follow automatically.')
        print('Automatic deletion is prohibited.')
        return
    if PAUSED.exists():
        print('Copying is paused. Use Resume Automatic Sync.command to continue.')
        return
    with (BASE / 'state/runner.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another copy is running; skipping this invocation.')
            return
        if action == 'prepare-health':
            for job in settings['jobs']:
                marker = Path(job['local']) / HEALTH
                if not marker.exists():
                    marker.write_text('Cloud Drive Sync health marker. Keep this file in both drives.\n')
                subprocess.run(rclone_args('copyto', marker, remote_join(job['remote'], HEALTH), '--immutable'), check=True)
            return
        if action == 'run' and not settings.get('initialized'):
            raise RuntimeError('Initial copying is not complete. Nothing was changed.')
        if action == 'initialize' and settings.get('initialized'):
            raise RuntimeError('Already initialized. Use run.')
        for job in settings['jobs']:
            if action == 'initialize' and job.get('initialized'):
                continue
            execute(job, initial=action == 'initialize', dry_run=action == 'preview')
            if action != 'preview':
                settings['initialized'] = all(j.get('initialized') for j in settings['jobs'])
                save_json(CONFIG, settings)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.CalledProcessError) as error:
        try:
            status = json.loads((BASE / 'status.json').read_text()) if (BASE / 'status.json').exists() else {}
            status.update(state='needs_attention', error=str(error), delete_policy='never')
            save_json(BASE / 'status.json', status)
        except Exception:
            pass
        print(str(error), file=sys.stderr)
        sys.exit(1)
