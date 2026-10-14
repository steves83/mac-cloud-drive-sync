import sys,tempfile,json,os
from pathlib import Path
import sync

original=sync.BASE
with tempfile.TemporaryDirectory(prefix='cloud-copy-protection-') as temp:
    root=Path(temp);left=root/'icloud';right=root/'google';left.mkdir();right.mkdir()
    (root/'logs').mkdir();(root/'state').mkdir()
    (root/'filters.txt').write_text((original/'filters.txt').read_text())
    sync.BASE=root
    job={'name':'test','local':str(left),'remote':str(right),'filters':'filters.txt','initialized':False}
    for p in [left,right]:(p/sync.HEALTH).write_text('health marker\n')
    for n in range(12):(left/('file-%02d.txt'%n)).write_text('original %d\n'%n)
    (right/'from-google.txt').write_text('Google addition\n')
    (left/'nested/empty').mkdir(parents=True)
    sync.execute(job,initial=True)
    assert (right/'file-00.txt').read_text()=='original 0\n'
    assert (left/'from-google.txt').read_text()=='Google addition\n'
    assert (right/'nested/empty').is_dir()
    print('PASS: additions, nested folders, and empty folders copy both ways',flush=True)
    (left/'file-00.txt').unlink()
    (right/'from-google.txt').unlink()
    sync.execute(job)
    assert (left/'file-00.txt').read_text()=='original 0\n'
    assert (right/'from-google.txt').read_text()=='Google addition\n'
    print('PASS: deletion on either side is restored; the other side is never deleted',flush=True)
    (left/'file-01.txt').rename(left/'renamed.txt')
    sync.execute(job)
    assert all((p/'file-01.txt').exists() and (p/'renamed.txt').exists() for p in [left,right])
    print('PASS: rename retains old and new names in both locations',flush=True)
    (left/'file-02.txt').write_text('iCloud updated document with more text\n')
    (right/'file-03.txt').write_text('Google updated document with more text\n')
    sync.execute(job)
    assert (right/'file-02.txt').read_text()=='iCloud updated document with more text\n'
    assert (left/'file-03.txt').read_text()=='Google updated document with more text\n'
    for p in [left,right]:
        history={x.read_text() for x in (p/sync.HISTORY).rglob('*') if x.is_file()}
        assert 'original 2\n' in history and 'original 3\n' in history
    print('PASS: edits update both locations; replaced versions remain in recovery folders on both sides',flush=True)
    (left/'file-04.txt').write_text('iCloud conflict version\n')
    (right/'file-04.txt').write_text('Google conflict version that is newer\n')
    sync.execute(job)
    for p in [left,right]:
        contents={x.read_text() for x in p.rglob('*') if x.is_file()}
        assert 'iCloud conflict version\n' in contents and 'Google conflict version that is newer\n' in contents
    print('PASS: both conflicting edits are retained in each location',flush=True)
    for n in range(5,12):(left/('file-%02d.txt'%n)).unlink()
    sync.execute(job)
    assert all((left/('file-%02d.txt'%n)).exists() and (right/('file-%02d.txt'%n)).exists() for n in range(5,12))
    print('PASS: even mass deletion is restored instead of propagating',flush=True)
    (right/sync.HEALTH).unlink()
    (left/'must-not-upload.txt').write_text('health guard\n')
    try:sync.execute(job)
    except RuntimeError:pass
    else:raise AssertionError('Missing health marker must stop the copy')
    assert not (right/'must-not-upload.txt').exists()
    print('PASS: offline/missing marker stops changes',flush=True)
    sync.BASE=original
    sync.save_json(original/'no-deletion-verification.json',{'passed':True,'policy':'never','checks':['additions both ways','deletions restored both ways','renames retain both names','replaced versions archived in both locations','conflicting versions retained in both locations','mass deletions restored','health guard stops changes']})
