"""Verify complete coverage, generate reports and archive actual run evidence."""
from pathlib import Path
import argparse, datetime, hashlib, importlib.metadata, json, os, shutil, statistics, subprocess, sys, tarfile
PROJECT=Path(__file__).resolve().parent
sys.path.insert(0,str(PROJECT/'codex104'))
from report import generate
from run import all_tasks, digest, write, stats, PIN
sys.path.insert(0,str(PROJECT))
import native104
p=argparse.ArgumentParser();p.add_argument('--status',action='store_true')
p.add_argument('--harness',choices=sorted(native104.DEFAULT_MODEL),default='codex');p.add_argument('--model',default=None)
p.add_argument('--trial',type=int,default=None);p.add_argument('--budget',type=float,default=None);a=p.parse_args()
OUT=native104.configure(a.harness,a.model,a.trial,a.budget)
ROOT=native104.ROOT
ORIGINAL=a.trial is None  # the original 104x1 run keeps its historical test log and archive name
ARCHIVE_NAME=OUT.name if ORIGINAL else f'{OUT.parent.name}-{OUT.name}'
rows=[json.loads(f.read_text()) for f in sorted(OUT.glob('runs/*/query*/result.json'))]
print(json.dumps({'finished':len(rows),'correct':sum(r.get('passed') is True for r in rows),'unscored':sum(r.get('passed') is None for r in rows),'statuses':{s:sum(r['status']==s for r in rows) for s in sorted({r['status'] for r in rows})}},indent=2),flush=True)
if a.status:sys.exit(0)
expected=set(all_tasks(ROOT));actual={(r['dataset'],r['query']) for r in rows}
assert expected==actual and len(rows)==104,'Coverage incomplete'
assert all(r['status']=='completed' and r.get('grading_status')=='scored' and isinstance(r.get('passed'),bool) for r in rows),'Unscored trials need review'
assert not list(OUT.glob('runs/*/query*/client/auth.json')),'Credential cleanup incomplete'
if ORIGINAL and (PROJECT/'review-notes.json').exists():  # notes describe the original run's failures only
 (OUT/'reports').mkdir(exist_ok=True);shutil.copyfile(PROJECT/'review-notes.json',OUT/'reports/review-notes.json')
summary=generate(OUT)
summary.update(question_micro_accuracy=sum(r['passed'] for r in rows)/104,
 total_input_tokens=sum(r.get('input_tokens',0) for r in rows),
 total_cached_input_tokens=sum(r.get('cached_input_tokens',0) for r in rows),
 total_output_tokens=sum(r.get('output_tokens',0) for r in rows),
 total_tool_calls=sum(r.get('tool_calls',0) for r in rows),
 median_duration_s=statistics.median(r['duration_s'] for r in rows),
 total_agent_duration_s=sum(r['duration_s'] for r in rows))
write(OUT/'reports/aggregate_metrics.json',summary)

excluded=[json.loads(p.read_text()) for p in sorted(OUT.glob('excluded-attempts/*/*/*/result.json'))]
usage_fields=['input_tokens','cached_input_tokens','cache_write_input_tokens','output_tokens','reasoning_output_tokens']
usage_rows=[]
for f in sorted(list(OUT.glob('runs/*/query*/events.jsonl'))+list(OUT.glob('excluded-attempts/*/*/*/events.jsonl'))):
    st,_=stats(f)  # same parser for Codex and Claude Code events
    usage_rows.append({'trace':str(f.relative_to(OUT)),'excluded':'excluded-attempts' in f.parts,'usage_available':st['usage_available'],**{k:st[k] for k in usage_fields}})
accounting={'valid_trials':len(rows),'excluded_scored_attempts':len(excluded),'recorded_usage_all_attempts':{k:sum(r[k] for r in usage_rows) for k in usage_fields},'attempts_without_terminal_usage':sum(not r['usage_available'] for r in usage_rows),'note':'Excluded harness attempts are not counted in accuracy. Their recorded usage remains included here. Interrupted calls may lack terminal usage; this is not a billing total.','attempts':usage_rows}
write(OUT/'reports/attempt-accounting.json',accounting)
shutil.copyfile(PROJECT/'HARNESS_CORRECTION.md',OUT/'reports/HARNESS_CORRECTION.md')
notes=PROJECT/'review-notes.json'
if ORIGINAL and notes.exists():shutil.copyfile(notes,OUT/'reports/review-notes.json')

evidence=[]
for r in rows:
 if r['passed']:continue
 f=OUT/'runs'/r['dataset']/('query'+str(r['query']))
 commands=json.loads((f/'commands.json').read_text())
 evidence.append({'dataset':r['dataset'],'query':r['query'],'official_grading':json.loads((f/'grading.json').read_text()),'answer':r['answer'],'command_errors':[{'command':c.get('command'),'exit_code':c.get('exit_code'),'output':c.get('aggregated_output','')[-1800:]} for c in commands if c.get('exit_code') not in (0,None)],'last_commands':[{'command':c.get('command'),'output':c.get('aggregated_output','')[-1800:]} for c in commands[-2:]]})
write(OUT/'reports/failure_evidence.json',evidence)
packages={d.metadata['Name']:d.version for d in importlib.metadata.distributions() if d.metadata.get('Name')}
write(OUT/'runtime-packages.json',{'python':sys.version,'packages':dict(sorted(packages.items()))})
write(OUT/'runtime-images.json',{'images':{n:{'sha256':digest(PROJECT/'runtime'/n),'bytes':(PROJECT/'runtime'/n).stat().st_size} for n in ['postgres17.sif','mongo8.sif']},'singularity':subprocess.check_output(['singularity','--version'],text=True).strip()})
source=OUT/'source-snapshot';source.mkdir(exist_ok=True)
if (OUT/'runs/stockindex/query1/client/settings.json').exists():  # Claude Code settings used by every task
 shutil.copyfile(OUT/'runs/stockindex/query1/client/settings.json',OUT/'claude-settings.json')
for rel in ['native104.py','finalize104.py','codex104/run.py','codex104/preflight.py','codex104/report.py','codex104/test_protocol.py','dabbench/data.py','dabbench/core.py','requirements.txt','bootstrap.sh','HARNESS_CORRECTION.md','README.md','review-notes.json']:
 dest=source/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(PROJECT/rel,dest)
for ds,q in sorted(expected):
 d=ROOT/('query_'+ds);dest=OUT/'original-task-snapshot'/('query_'+ds)/('query'+str(q));dest.mkdir(parents=True,exist_ok=True)
 for n in ['query.json','validate.py','ground_truth.csv']:
  original=d/('query'+str(q))/n
  if original.exists():shutil.copyfile(original,dest/n)
 for n in ['db_description.txt','db_description_withhint.txt','db_config.yaml']:shutil.copyfile(d/n,dest.parent/n)

if ORIGINAL:
 test_log=(PROJECT/'strict-status/review104-65052546.log').read_text()
else:
 t=subprocess.run([sys.executable,'-m','unittest','-v','test_protocol'],cwd=PROJECT/'codex104',capture_output=True,text=True)
 test_log=t.stdout+t.stderr
assert '\nOK' in test_log and 'Ran 4 tests' in test_log,test_log[-2000:]
vdir=OUT/'verification';vdir.mkdir(exist_ok=True)
(vdir/'protocol-tests.log').write_text(test_log.split('\nOK')[0]+'\nOK\n')

keys=[k.read_bytes().strip() for k in native104.KEYS.values() if k.exists()]

# Keep one representative auto-downloaded plugin cache; all trajectories and
# per-client plugin revision markers remain intact. Original run directories are untouched.
plugin_caches=sorted(OUT.glob('runs/*/query*/client/.tmp/plugins'))
representative=plugin_caches[0] if plugin_caches else None
write(OUT/'archive-policy.json',{'preserve':'All CLI events, sessions, commands, answers, graders, final work files, source and provenance','omitted':'Repeated client/.tmp/plugins download caches except one representative','representative_cache':str(representative.relative_to(OUT)) if representative else None,'note':'Per-client plugins.sha markers are retained. Agent-deleted intermediate scripts remain in session tool-call/patch events; only surviving work files exist as standalone files.'})
def retained_paths():
    for base,dirs,names in os.walk(OUT,followlinks=False):
        base=Path(base)
        for name in list(dirs):
            d=base/name
            if name=='plugins' and base.name=='.tmp' and base.parent.name=='client' and d!=representative:
                dirs.remove(name)
            elif d.is_symlink():
                yield d;dirs.remove(name)
        for name in names:yield base/name

files=[]
for f in sorted(retained_paths()):
 if f.is_symlink():files.append({'path':str(f.relative_to(OUT)),'symlink':os.readlink(f)});continue
 if not f.is_file() or f.name in ['archive-manifest.json','ARCHIVE.json']:continue
 if keys:
  with f.open('rb') as stream:
   tail=b''
   for block in iter(lambda:stream.read(1024*1024),b''):
    assert not any(k in tail+block for k in keys),'Credential detected in '+str(f.relative_to(OUT))
    tail=block[-max(map(len,keys)):]
 files.append({'path':str(f.relative_to(OUT)),'bytes':f.stat().st_size,'sha256':digest(f)})
write(OUT/'archive-manifest.json',{'upstream_commit':PIN,'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':files,'data_note':'Dataset symlinks are preserved without duplicating original data. Restore pinned upstream assets using original-data-manifest.json.'})
archive_dir=Path('/home/minhyeok/dab-archives');archive_dir.mkdir(exist_ok=True)
archive=archive_dir/(ARCHIVE_NAME+'.tar.gz')
def archive_filter(i):
 if i.name.endswith('/ARCHIVE.json'):return None
 if i.name.endswith('/client/.tmp/plugins') and (representative is None or i.name!=OUT.name+'/'+str(representative.relative_to(OUT))):return None
 return i
with tarfile.open(archive,'w:gz',dereference=False) as tar:tar.add(OUT,arcname=OUT.name,filter=archive_filter)

with tarfile.open(archive,'r:gz') as tar:
    index={m.name:m for m in tar.getmembers()}
    for item in files:
        name=OUT.name+'/'+item['path']
        assert name in index,'Archive member missing: '+name
        if 'sha256' not in item:continue
        stream=tar.extractfile(index[name]);assert stream is not None
        h=hashlib.sha256()
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
        assert h.hexdigest()==item['sha256'],'Archive checksum mismatch: '+name
print('ARCHIVE_MEMBERS_VERIFIED',len(files),flush=True)

record={'path':str(archive),'sha256':digest(archive),'bytes':archive.stat().st_size,'files':len(files),'coverage':104,'datasets':17,'data_included':False,'full_trajectories_included':True}
write(OUT/'ARCHIVE.json',record)
(archive_dir/(ARCHIVE_NAME+'.tar.gz.sha256')).write_text(record['sha256']+'  '+archive.name+'\n')
dest=native104.results_dir();shutil.copytree(OUT/'reports',dest,dirs_exist_ok=True)
for n in ['protocol.json','ARCHIVE.json','original-data-manifest.json','runtime-packages.json','archive-manifest.json','harness-correction.json','database-preflight.json','archive-policy.json','runtime-images.json','claude-settings.json']:
 if (OUT/n).exists():shutil.copyfile(OUT/n,dest/n)
print('FINALIZED',json.dumps({'metrics':summary,'archive':record}),flush=True)
