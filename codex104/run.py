"""Terra / original DAB tasks / one Codex session per task.
The authors' native Codex driver is not public; this is a documented reconstruction.
"""
from __future__ import annotations
from pathlib import Path
import argparse,concurrent.futures,datetime,hashlib,importlib.util,json,os,shutil,signal,subprocess,sys,time,traceback
import yaml
from preflight import invocation,client_config,digest
PIN='61fb21e0766d775acae443f6074f5d498e95f938'

def write(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n');t.replace(p)

def all_tasks(root):
 return [(p.parent.parent.name[6:],int(p.parent.name[5:])) for p in sorted(Path(root).glob('query_*/query[0-9]*/query.json')) if p.parent.name[5:].isdigit()]

def prompt(root,ds,qid):
 d=Path(root)/('query_'+ds);v=json.loads((d/f'query{qid}/query.json').read_text());q=v if isinstance(v,str) else v['query']
 # Exact original task and context strings; no new agent instructions.
 description=(d/'db_description.txt').read_text().strip()+'\n\n'+(d/'db_description_withhint.txt').read_text().strip()
 return 'QUERY:\n'+q.strip()+'\n\nDATABASE DESCRIPTION:\n'+description

def official_grade(root,ds,qid,answer):
 path=Path(root)/f'query_{ds}/query{qid}/validate.py'
 # Run the unchanged query-specific validator in its expected working directory.
 code='''from pathlib import Path
import importlib.util,json,os,sys
p=Path(sys.argv[1]);os.chdir(p.parent);sys.path.insert(0,sys.argv[2])
s=importlib.util.spec_from_file_location("dab_official_validator",p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
r=m.validate(Path(sys.argv[3]).read_text())
if not isinstance(r,tuple) or len(r)!=2:raise ValueError("Unexpected original validator signature")
print(json.dumps({"passed":bool(r[0]),"reason":str(r[1])}))
'''
 try:
  r=subprocess.run([sys.executable,'-c',code,str(path),str(Path(root).resolve()),str(Path(answer).resolve())],capture_output=True,text=True,timeout=120)
  if r.returncode:raise RuntimeError(r.stderr[-3000:])
  d=json.loads(r.stdout.splitlines()[-1]);d.update(status='scored',validator_sha256=digest(path));return d
 except Exception as e:return {'passed':None,'status':'grader_error','reason':str(e),'validator_sha256':digest(path)}

def stats(path):
 out=dict(input_tokens=0,cached_input_tokens=0,output_tokens=0,tool_calls=0,command_calls=0,command_errors=0,api_errors=0)
 cmds=[];usage=False
 for line in Path(path).read_text(errors='replace').splitlines():
  try:e=json.loads(line)
  except ValueError:continue
  if e.get('type')=='turn.completed' and e.get('usage'):
   usage=True
   for k in ['input_tokens','cached_input_tokens','output_tokens']:out[k]+=e['usage'].get(k,0) or 0
  if e.get('type') in ['turn.failed','error']:out['api_errors']+=1
  if e.get('type')=='item.completed':
   i=e.get('item',{});kind=i.get('type')
   if kind in ['command_execution','mcp_tool_call','file_change','web_search']:out['tool_calls']+=1
   if kind=='command_execution':
    cmds.append(i);out['command_calls']+=1;out['command_errors']+=i.get('exit_code') not in (0,None)
 out['usage_available']=usage
 # Token estimate only; U-M invoices may apply different cache/context rates.
 out['estimated_cost_usd']=((out['input_tokens']-out['cached_input_tokens'])*2+out['cached_input_tokens']*.2+out['output_tokens']*12)/1e6 if usage else None
 return out,cmds

def one(project,root,out,ds,qid,sockets,preflight):
 trial=out/'runs'/ds/f'query{qid}'
 if (trial/'result.json').exists():return json.loads((trial/'result.json').read_text())
 trial.mkdir(parents=True,exist_ok=False)
 work=trial/'work';work.mkdir()
 home=Path(os.environ.get('SLURM_TMPDIR','/tmp'))/('dab-client-'+os.environ.get('SLURM_JOB_ID','local'))/(ds+'-q'+str(qid))
 home.mkdir(parents=True,mode=0o700,exist_ok=False)
 config=client_config(home)
 shutil.copyfile(root/f'query_{ds}/db_config.yaml',work/'db_config.yaml')
 source=prompt(root,ds,qid);(trial/'prompt.txt').write_text(source)
 env={'PGHOST':'/sockets','PGUSER':'dab_readonly','PGPORT':'5432','PGDATABASE':'postgres',
      'MONGO_URI':'mongodb://dab_readonly:dab_readonly@%2Fsockets%2Fmongodb-27017.sock/?authSource=admin'}
 # Runtime-only DB connection metadata is separate from the unmodified task prompt.
 write(work/'connections.json',{'postgres':{'host':'/sockets','user':'dab_readonly','port':5432},'mongodb':{'uri':env['MONGO_URI']}})
 binds=[str(root/f'query_{ds}/query_dataset')+':/work/query_dataset:ro',str(sockets)+':/sockets:ro']
 argv=invocation(project,trial,home,work,binds,env)+['codex','--ask-for-approval','never','exec','--json','--skip-git-repo-check',
       '--sandbox','workspace-write','--model','gpt-5.6-terra','--output-last-message','/work/answer.txt','-']
 record={'kind':'benchmark','model':'gpt-5.6-terra','dataset':ds,'query':qid,'trial':0,'condition':'description+hints',
         'upstream_commit':PIN,'harness':'Codex CLI','harness_reconstruction':True,'authors_driver_unavailable':True,
         'question_sha256':digest(root/f'query_{ds}/query{qid}/query.json'),'prompt_sha256':digest(trial/'prompt.txt'),
         'image_sha256':preflight['image_sha256'],'codex_sha256':preflight['codex_sha256'],
         'host':os.uname().nodename,'slurm_job_id':os.getenv('SLURM_JOB_ID'),'argv':argv,
         'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'running','passed':None}
 write(trial/'manifest.json',record)
 key=Path('/home/minhyeok/.config/dab/key').read_text().strip();auth=config/'auth.json'
 start=time.monotonic();returncode=None
 try:
  auth.write_text(json.dumps({'auth_mode':'apikey','OPENAI_API_KEY':key}));auth.chmod(0o600)
  with (trial/'events.jsonl').open('w') as stdout,(trial/'stderr.log').open('w') as stderr:
   p=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,text=True,start_new_session=True)
   try:p.communicate(source,timeout=5400)
   except subprocess.TimeoutExpired:
    os.killpg(p.pid,signal.SIGTERM)
    try:p.wait(timeout=10)
    except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
    record['status']='infrastructure_deadline'
   returncode=p.returncode
   if record['status']=='running':record['status']='completed' if returncode==0 else 'runtime_error'
 except Exception as e:record.update(status='launcher_error',error=str(e).replace(key,'[REDACTED]'))
 finally:
  auth.unlink(missing_ok=True)
  sessions=home/'.codex/sessions'
  if sessions.exists():shutil.copytree(sessions,trial/'codex-sessions')
 # Remove accidental exact-key emissions from every retained client/session artifact.
 for p in trial.rglob('*'):
  if p.is_file() and p.stat().st_size<50_000_000:
   b=p.read_bytes()
   if key.encode() in b:p.write_bytes(b.replace(key.encode(),b'[REDACTED]'))
 answer=work/'answer.txt'
 if not answer.exists():answer.write_text('')
 st,commands=stats(trial/'events.jsonl') if (trial/'events.jsonl').exists() else ({'usage_available':False,'estimated_cost_usd':None},[])
 grading=official_grade(root,ds,qid,answer);write(trial/'grading.json',grading);write(trial/'commands.json',commands)
 record.update(duration_s=time.monotonic()-start,returncode=returncode,answer=answer.read_text(),
               grading_status=grading['status'],passed=grading['passed'] if record['status']=='completed' else None,
               finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),**st)
 write(trial/'manifest.json',record);write(trial/'result.json',record)
 print('RESULT',ds,qid,record['status'],record['passed'],record.get('estimated_cost_usd'),flush=True)
 return record

def services(project,root,rt):
 rt.mkdir(parents=True,exist_ok=False);sock=rt/'sockets';sock.mkdir(mode=0o700)
 pg=project/'runtime/postgres17.sif';mongo=project/'runtime/mongo8.sif'
 def run(cmd,**kw):return subprocess.run(cmd,check=True,**kw)
 pgbase=['singularity','exec','--bind',str(rt)+':'+str(rt),str(pg)]
 pgdata=rt/'pgdata';run(pgbase+['/usr/lib/postgresql/17/bin/initdb','-D',str(pgdata),'-U','postgres','--auth-local=trust','--auth-host=reject'])
 run(pgbase+['/usr/lib/postgresql/17/bin/pg_ctl','-D',str(pgdata),'-l',str(rt/'postgres.log'),'-o',f"-k {sock} -c listen_addresses=''",'start'])
 ps=pgbase+['psql','-h',str(sock),'-U','postgres','-v','ON_ERROR_STOP=1']
 run(ps+['-d','postgres','-c',"CREATE ROLE dab_readonly LOGIN; ALTER ROLE dab_readonly SET default_transaction_read_only=on;"])
 mb=['singularity','exec','--bind',str(rt)+':'+str(rt),str(mongo)]
 mdata=rt/'mongodata';mdata.mkdir()
 # Start unauthenticated only during original dump loading; then restart with auth.
 run(mb+['mongod','--dbpath',str(mdata),'--unixSocketPrefix',str(sock),'--bind_ip','127.0.0.1','--port','27017','--fork','--logpath',str(rt/'mongo.log')])
 for ds in sorted({d for d,q in all_tasks(root)}):
  cfg=yaml.safe_load((root/f'query_{ds}/db_config.yaml').read_text())['db_clients']
  for c in cfg.values():
   if c['db_type']=='postgres':
    name=c['db_name'];run(pgbase+['createdb','-h',str(sock),'-U','postgres','--encoding=UTF8','--lc-collate=C','--lc-ctype=C','--template=template0',name])
    with (root/f'query_{ds}'/c['sql_file']).open('rb') as f:run(ps+['-d',name],stdin=f,stdout=subprocess.DEVNULL)
    run(ps+['-d',name,'-c','GRANT USAGE ON SCHEMA public TO dab_readonly; GRANT SELECT ON ALL TABLES IN SCHEMA public TO dab_readonly;'])
   elif c['db_type']=='mongo':
    run(['singularity','exec','--bind',str(rt)+':'+str(rt),'--bind',str(root)+':'+str(root)+':ro',str(mongo),
         'mongorestore','--host',str(sock/'mongodb-27017.sock'),'--nsInclude',c['db_name']+'.*',str(root/f'query_{ds}'/c['dump_folder'])])
  print('DATABASES_LOADED',ds,flush=True)
 script="db.getSiblingDB('admin').createUser({user:'dab_readonly',pwd:'dab_readonly',roles:[{role:'readAnyDatabase',db:'admin'}]})"
 run(mb+['mongosh','--host',str(sock/'mongodb-27017.sock'),'--quiet','--eval',script])
 run(mb+['mongod','--dbpath',str(mdata),'--shutdown'])
 run(mb+['mongod','--dbpath',str(mdata),'--unixSocketPrefix',str(sock),'--bind_ip','127.0.0.1','--port','27017','--auth','--fork','--logpath',str(rt/'mongo.log')])
 return sock

def main():
 p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--preflight',type=Path,required=True);p.add_argument('--workers',type=int,default=4);p.add_argument('--pilot',action='store_true');a=p.parse_args()
 project=a.project.resolve();root=Path('/home/minhyeok/dab-reproduction');out=a.out.resolve()
 if not os.getenv('SLURM_JOB_ID'):raise RuntimeError('A Slurm allocation is required')
 if subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()!=PIN:raise RuntimeError('Source pin changed')
 pf=json.loads(a.preflight.read_text())
 if not pf.get('passed'):raise RuntimeError('No passing runtime preflight')
 if digest(project/'runtime/strict-python312.sif')!=pf['image_sha256'] or digest(Path('/home/minhyeok/.local/bin/codex114').resolve())!=pf['codex_sha256']:raise RuntimeError('Runtime changed since preflight')
 changed=subprocess.check_output(['git','-C',str(root),'diff','HEAD','--name-only'],text=True).splitlines()
 if any('/query_dataset/' not in x for x in changed):raise RuntimeError('Original task, prompt or grader was modified')
 tasks=all_tasks(root);assert len(tasks)==104
 manifest=json.loads((root.parent/'data-manifest.json').read_text())
 if manifest.get('upstream_commit')!=PIN or len(manifest.get('queries',[]))!=104 or not all(f['verified'] for f in manifest['files']):raise RuntimeError('Full original data manifest is not verified')
 out.mkdir(parents=True,exist_ok=True)
 shutil.copyfile(root.parent/'data-manifest.json',out/'original-data-manifest.json')
 write(out/'protocol.json',{'model':'gpt-5.6-terra','tasks':tasks,'trials_per_query':1,'condition':'description+hints','upstream_commit':PIN,'reconstruction_limit':'Authors native Codex driver unavailable; exact task text/context and graders preserved; Codex default prompts and tools retained.'})
 if a.pilot:
  sockets=out/'pilot-sockets';sockets.mkdir(exist_ok=True);tasks=[('stockindex',1)]
 else:sockets=services(project,root,Path(os.environ.get('SLURM_TMPDIR','/tmp'))/('dab-services-'+os.environ['SLURM_JOB_ID']))
 errors=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
  jobs={pool.submit(one,project,root,out,d,q,sockets,pf):(d,q) for d,q in tasks}
  for f in concurrent.futures.as_completed(jobs):
   try:f.result()
   except Exception as e:errors.append({'task':jobs[f],'error':str(e),'traceback':traceback.format_exc()});write(out/'launcher-errors.json',errors)
 from report import generate
 generate(out)
 if errors:raise RuntimeError('Some launcher failures; inspect launcher-errors.json')

if __name__=='__main__':main()
