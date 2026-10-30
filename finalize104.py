"""Verify complete coverage, generate reports and archive actual run evidence."""
from pathlib import Path
import argparse, datetime, hashlib, importlib.metadata, json, os, shutil, statistics, subprocess, sys, tarfile
PROJECT=Path(__file__).resolve().parent
sys.path.insert(0,str(PROJECT/'codex104'))
from report import generate
from run import all_tasks, digest, write, PIN
OUT=Path('/home/minhyeok/dab-artifacts/terra-native-104x1')
ROOT=Path('/home/minhyeok/dab-reproduction')
p=argparse.ArgumentParser();p.add_argument('--status',action='store_true');a=p.parse_args()
rows=[json.loads(f.read_text()) for f in sorted(OUT.glob('runs/*/query*/result.json'))]
print(json.dumps({'finished':len(rows),'correct':sum(r.get('passed') is True for r in rows),'unscored':sum(r.get('passed') is None for r in rows),'statuses':{s:sum(r['status']==s for r in rows) for s in sorted({r['status'] for r in rows})}},indent=2),flush=True)
if a.status:sys.exit(0)
expected=set(all_tasks(ROOT));actual={(r['dataset'],r['query']) for r in rows}
assert expected==actual and len(rows)==104,'Coverage incomplete'
assert all(r['status']=='completed' and r.get('grading_status')=='scored' and isinstance(r.get('passed'),bool) for r in rows),'Unscored trials need review'
assert not list(OUT.glob('runs/*/query*/client/auth.json')),'Credential cleanup incomplete'
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
for f in sorted(OUT.glob('**/events.jsonl')):
    usage={k:0 for k in usage_fields};available=False
    for line in f.read_text(errors='replace').splitlines():
        try:e=json.loads(line)
        except ValueError:continue
        if e.get('type')=='turn.completed' and e.get('usage'):
            available=True
            for k in usage_fields:usage[k]+=e['usage'].get(k,0) or 0
    usage_rows.append({'trace':str(f.relative_to(OUT)),'excluded':'excluded-attempts' in f.parts,'usage_available':available,**usage})
accounting={'valid_trials':len(rows),'excluded_scored_attempts':len(excluded),'recorded_usage_all_attempts':{k:sum(r[k] for r in usage_rows) for k in usage_fields},'attempts_without_terminal_usage':sum(not r['usage_available'] for r in usage_rows),'note':'Excluded harness attempts are not counted in accuracy. Their recorded usage remains included here. Interrupted calls may lack terminal usage; this is not a billing total.','attempts':usage_rows}
write(OUT/'reports/attempt-accounting.json',accounting)
notes=PROJECT/'review-notes.json'
if notes.exists():shutil.copyfile(notes,OUT/'reports/review-notes.json')

evidence=[]
for r in rows:
 if r['passed']:continue
 f=OUT/'runs'/r['dataset']/('query'+str(r['query']))
 commands=json.loads((f/'commands.json').read_text())
 evidence.append({'dataset':r['dataset'],'query':r['query'],'official_grading':json.loads((f/'grading.json').read_text()),'answer':r['answer'],'command_errors':[{'command':c.get('command'),'exit_code':c.get('exit_code'),'output':c.get('aggregated_output','')[-1800:]} for c in commands if c.get('exit_code') not in (0,None)],'last_commands':[{'command':c.get('command'),'output':c.get('aggregated_output','')[-1800:]} for c in commands[-2:]]})
write(OUT/'reports/failure_evidence.json',evidence)
packages={d.metadata['Name']:d.version for d in importlib.metadata.distributions() if d.metadata.get('Name')}
write(OUT/'runtime-packages.json',{'python':sys.version,'packages':dict(sorted(packages.items()))})
source=OUT/'source-snapshot';source.mkdir(exist_ok=True)
for rel in ['native104.py','finalize104.py','codex104/run.py','codex104/preflight.py','codex104/report.py','dabbench/data.py','dabbench/core.py','requirements.txt','bootstrap.sh']:
 dest=source/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(PROJECT/rel,dest)
for ds,q in sorted(expected):
 d=ROOT/('query_'+ds);dest=OUT/'original-task-snapshot'/('query_'+ds)/('query'+str(q));dest.mkdir(parents=True,exist_ok=True)
 for n in ['query.json','validate.py']:shutil.copyfile(d/('query'+str(q))/n,dest/n)
 for n in ['db_description.txt','db_description_withhint.txt','db_config.yaml']:shutil.copyfile(d/n,dest.parent/n)
key=Path('/home/minhyeok/.config/dab/key').read_bytes().strip()
files=[]
for f in sorted(OUT.rglob('*')):
 if f.is_symlink():files.append({'path':str(f.relative_to(OUT)),'symlink':os.readlink(f)});continue
 if not f.is_file() or f.name in ['archive-manifest.json','ARCHIVE.json']:continue
 if key:
  with f.open('rb') as stream:
   tail=b''
   for block in iter(lambda:stream.read(1024*1024),b''):
    assert key not in tail+block,'Credential detected in '+str(f.relative_to(OUT))
    tail=block[-len(key):]
 files.append({'path':str(f.relative_to(OUT)),'bytes':f.stat().st_size,'sha256':digest(f)})
write(OUT/'archive-manifest.json',{'upstream_commit':PIN,'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':files,'data_note':'Dataset symlinks are preserved without duplicating original data. Restore pinned upstream assets using original-data-manifest.json.'})
archive_dir=Path('/home/minhyeok/dab-archives');archive_dir.mkdir(exist_ok=True)
archive=archive_dir/'terra-native-104x1.tar.gz'
with tarfile.open(archive,'w:gz',dereference=False) as tar:tar.add(OUT,arcname=OUT.name,filter=lambda i:None if i.name.endswith('/ARCHIVE.json') else i)
record={'path':str(archive),'sha256':digest(archive),'bytes':archive.stat().st_size,'files':len(files),'coverage':104,'datasets':17,'data_included':False,'full_trajectories_included':True}
write(OUT/'ARCHIVE.json',record)
(archive_dir/'terra-native-104x1.tar.gz.sha256').write_text(record['sha256']+'  '+archive.name+'\n')
dest=PROJECT/'results/terra-native-104x1';shutil.copytree(OUT/'reports',dest,dirs_exist_ok=True)
for n in ['protocol.json','ARCHIVE.json','original-data-manifest.json','runtime-packages.json','archive-manifest.json','harness-correction.json','database-preflight.json']:shutil.copyfile(OUT/n,dest/n)
print('FINALIZED',json.dumps({'metrics':summary,'archive':record}),flush=True)
