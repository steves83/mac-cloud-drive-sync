"""Resume the additive initial copy, then activate the five-minute schedule."""
from pathlib import Path
import datetime as dt
import json
import subprocess
import sys

BASE=Path(__file__).resolve().parent
APP=Path.home()/'Applications/Cloud Drive Sync.app/Contents/MacOS/CloudDriveSync'
if (BASE/'PAUSED').exists():sys.exit(0)
settings=json.loads((BASE/'settings.json').read_text())
if settings.get('delete_policy')!='never':
    print('Automatic deletion is prohibited.',flush=True);sys.exit(1)
if not json.loads((BASE/'no-deletion-verification.json').read_text()).get('passed'):
    print('No-deletion verification has not passed.',flush=True);sys.exit(1)
if not json.loads((BASE/'cloud-no-deletion-verification.json').read_text()).get('passed'):
    print('Cloud-copy verification has not passed.',flush=True);sys.exit(1)
if not settings.get('initialized'):
    result=subprocess.run([str(APP),'initialize'])
    if result.returncode:
        print('Initial copy stopped safely; it will retry. No deletions are propagated.',flush=True)
        sys.exit(result.returncode)
if (BASE/'PAUSED').exists():sys.exit(0)
result=subprocess.run([str(APP),'enable'])
if result.returncode:sys.exit(result.returncode)
p=BASE/'SETUP_STATUS.json';state=json.loads(p.read_text());state.update(full_initial_merge_started=True,full_initial_merge_completed=True,five_minute_schedule_loaded=True,delete_policy='never',completed=dt.datetime.now().astimezone().isoformat());p.write_text(json.dumps(state,indent=2))
p=Path.home()/'Applications/Cloud Drive Sync/Read Me.txt';p.write_text('Cloud Drive Sync is active. It copies every five minutes while this Mac is awake and you are logged in.\n\nAutomatic deletion is NEVER allowed. Missing files are restored from the other side. Replaced versions stay in recovery folders in both clouds.\n\nDouble-click Check Sync Status.command for the latest result.\n')
print('Initial copy complete. Five-minute copying is active. Automatic deletion is prohibited.',flush=True)
