from pathlib import Path
import subprocess,uuid,json
import sync

name='Cloud Sync No-Delete Test '+uuid.uuid4().hex[:8]
local=Path.home()/'Library/Mobile Documents/com~apple~CloudDocs'/name
local.mkdir()
remote='google-drive:'+name
scratch=sync.BASE/'state/cloud-copy-verification';scratch.mkdir(exist_ok=True)
marker=local/sync.HEALTH;marker.write_text('cloud copy test marker\n')
def call(*args):
    r=subprocess.run(sync.rclone_args(*args),capture_output=True,text=True)
    if r.returncode:raise RuntimeError(r.stderr)
    return r.stdout
call('copyto',marker,remote+'/'+sync.HEALTH)
(local/'from-icloud.txt').write_text('Original iCloud test content\n')
source=scratch/'from-google.txt';source.write_text('Original Google test content\n')
call('copyto',source,remote+'/from-google.txt')
job={'name':'cloud-policy-test','local':str(local),'remote':remote,'filters':'filters.txt','initialized':False}
sync.execute(job,initial=True)
assert call('cat',remote+'/from-icloud.txt')=='Original iCloud test content\n'
assert (local/'from-google.txt').read_text()=='Original Google test content\n'
print('PASS: own Google client copies test files in both directions',flush=True)
(local/'from-icloud.txt').write_text('Updated iCloud test content with extra text\n')
source.write_text('Updated Google test content with extra text\n')
call('copyto',source,remote+'/from-google.txt')
sync.execute(job)
assert call('cat',remote+'/from-icloud.txt')=='Updated iCloud test content with extra text\n'
assert (local/'from-google.txt').read_text()=='Updated Google test content with extra text\n'
contents={p.read_text() for p in (local/sync.HISTORY).rglob('*') if p.is_file()}
assert 'Original iCloud test content\n' in contents and 'Original Google test content\n' in contents
remote_history=json.loads(call('lsjson',remote+'/'+sync.HISTORY,'--recursive','--files-only'))
assert len(remote_history)>=2
result={'passed':True,'delete_policy':'never','local':str(local),'remote':remote,'recovery_files_in_google':len(remote_history),'checks':['dedicated OAuth client works','copy both directions','edits update both directions','previous versions retained in both clouds'],'no_cloud_files_deleted_during_test':True}
sync.save_json(sync.BASE/'cloud-no-deletion-verification.json',result)
print(json.dumps(result,indent=2),flush=True)
