"""104x1 Codex evaluation with an explicitly tested native bubblewrap sandbox."""
from pathlib import Path
import argparse, concurrent.futures, datetime, errno, json, os, shutil, signal, subprocess, sys, time, urllib.parse, yaml
PROJECT=Path(__file__).resolve().parent
sys.path.insert(0,str(PROJECT/'codex104'))
from run import all_tasks, prompt, official_grade, stats, services, write, digest, PIN
from report import generate
ROOT=Path('/home/minhyeok/dab-reproduction')
BIN=Path('/home/minhyeok/.local/bin/codex')
OUT=Path('/home/minhyeok/dab-artifacts/terra-native-104x1')
MODEL='gpt-5.6-terra'

def setup(folder,dataset,sockets):
    work=folder/'work'; work.mkdir(parents=True,exist_ok=True)
    home=folder/'client'; home.mkdir(mode=0o700,exist_ok=True)
    tmp=work/'tmp';tmp.mkdir(exist_ok=True)
    data=ROOT/f'query_{dataset}/query_dataset'
    if data.exists() and not (work/'query_dataset').exists():
        (work/'query_dataset').symlink_to(data,target_is_directory=True)
    cfg=ROOT/f'query_{dataset}/db_config.yaml'
    shutil.copyfile(cfg,work/'db_config.yaml')
    rules={str(BIN.resolve().parent):'read',':minimal':'read',str(work):'write',str(PROJECT/'strict/.venv'):'read',
           str(Path(sys.executable).resolve().parent.parent):'read'}
    for p in ['/sw','/etc','/usr','/lib','/lib64','/bin','/sbin']:
        if Path(p).exists():rules[p]='read'
    if data.exists():rules[str(data)]='read'
    if sockets:rules[str(sockets)]='read'
    config='model_provider = "toolkit"\nmodel = "'+MODEL+'"\nweb_search = "disabled"\ndefault_permissions = "dab"\n'
    config+='[features]\nuse_linux_sandbox_bwrap = true\nshell_snapshot = false\nnetwork_proxy = true\n'
    config+='[model_providers.toolkit]\nname = "UM GPT Toolkit"\nbase_url = "https://api.toolkit.umgpt.umich.edu/v1"\nwire_api = "responses"\nrequires_openai_auth = true\n'
    config+='[permissions.dab.filesystem]\n'
    config+=''.join(json.dumps(k)+' = '+json.dumps(v)+'\n' for k,v in rules.items())
    config+='[permissions.dab.network]\nenabled = true\ndangerously_allow_all_unix_sockets = true\nallow_upstream_proxy = false\n[permissions.dab.network.domains]\n'
    (home/'config.toml').write_text(config)
    env=os.environ.copy()
    env.update(CODEX_HOME=str(home),TMPDIR=str(tmp),PYTHONPATH=str(PROJECT/'strict/.venv/lib/python3.12/site-packages'),
               PATH=str(Path(sys.executable).parent)+':'+env.get('PATH',''),NO_PROXY='',no_proxy='')
    if sockets:
        uri='mongodb://dab_readonly:dab_readonly@'+urllib.parse.quote(str(sockets/'mongodb-27017.sock'),safe='')+'/?authSource=admin'
        env.update(PGHOST=str(sockets),PGUSER='dab_readonly',PGPORT='5432',MONGO_URI=uri)
        write(work/'connections.json',{'postgres':{'host':str(sockets),'user':'dab_readonly','port':5432},'mongodb':{'uri':uri}})
    return work,home,env

def preflight():
    folder=OUT/'preflight'/datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
    work,home,env=setup(folder,'stockindex',None)
    blocked=ROOT/'query_stockindex/query1/validate.py'
    outside=folder/'forbidden.txt';outside.write_text('private-sentinel')
    code="""import pathlib,socket,errno
import duckdb,pandas,pyarrow,psycopg2,pymongo
p=pathlib.Path('allowed.txt');p.write_text('ok');assert p.read_text()=='ok'
assert pathlib.Path('query_dataset').exists()
for p in BLOCKED:
    try: pathlib.Path(p).read_bytes()
    except (PermissionError,FileNotFoundError): pass
    else: raise AssertionError('Unauthorized read: '+p)
try: pathlib.Path(OUTSIDE).write_text('changed')
except (PermissionError,FileNotFoundError): pass
else: pass # hidden parent may be an ephemeral sandbox directory
try: socket.create_connection(('1.1.1.1',443),3)
except OSError as e: assert e.errno in (errno.EPERM,errno.EACCES,errno.ENETUNREACH),repr(e)
else: raise AssertionError('Network not blocked')
print('NATIVE_ISOLATION_AND_NETWORK_OK')
""".replace('BLOCKED',repr([str(blocked),str(outside),'/home/minhyeok/.config/dab/key'])).replace('OUTSIDE',repr(str(outside)))
    cmd=[str(BIN),'-C',str(work),'sandbox','--',sys.executable,'-c',code]
    r=subprocess.run(cmd,cwd=work,env=env,capture_output=True,text=True,timeout=90)
    result={'passed':r.returncode==0 and 'NATIVE_ISOLATION_AND_NETWORK_OK' in r.stdout and outside.read_text()=='private-sentinel',
            'stdout':r.stdout,'stderr':r.stderr,'returncode':r.returncode,'binary_sha256':digest(BIN),
            'version':subprocess.check_output([str(BIN),'--version'],text=True).strip(),
            'config':(home/'config.toml').read_text(),'inference_calls':0}
    write(folder/'checks.json',result);write(OUT/'preflight-latest.json',result)
    print(json.dumps(result),flush=True)
    if not result['passed']:raise RuntimeError('Native isolation preflight failed')
    return result

def one(ds,qid,sockets,pf):
    folder=OUT/'runs'/ds/f'query{qid}'
    if (folder/'result.json').exists():return json.loads((folder/'result.json').read_text())
    folder.mkdir(parents=True,exist_ok=False)
    work,home,env=setup(folder,ds,sockets)
    source=prompt(ROOT,ds,qid);(folder/'prompt.txt').write_text(source)
    answer=work/'answer.txt'
    cmd=[str(BIN),'-C',str(work),'--ask-for-approval','never','exec','--json','--skip-git-repo-check',
         '--model',MODEL,'--output-last-message',str(answer),'-']
    record={'model':MODEL,'dataset':ds,'query':qid,'trial':0,'condition':'description+hints',
            'upstream_commit':PIN,'harness':'native Codex CLI 0.166.0','harness_reconstruction':True,'sandbox_revision':'unix-proxy-v2',
            'binary_sha256':pf['binary_sha256'],'prompt_sha256':digest(folder/'prompt.txt'),
            'status':'running','passed':None,'slurm_job_id':os.getenv('SLURM_JOB_ID'),
            'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    write(folder/'manifest.json',record)
    key=Path('/home/minhyeok/.config/dab/key').read_text().strip()
    auth=home/'auth.json';auth.write_text(json.dumps({'auth_mode':'apikey','OPENAI_API_KEY':key}));auth.chmod(0o600)
    start=time.monotonic();rc=None
    try:
        with (folder/'events.jsonl').open('w') as out,(folder/'stderr.log').open('w') as err:
            proc=subprocess.Popen(cmd,cwd=work,env=env,stdin=subprocess.PIPE,stdout=out,stderr=err,text=True,start_new_session=True)
            try:proc.communicate(source,timeout=5400)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid,signal.SIGTERM)
                try:proc.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
                record['status']='infrastructure_deadline'
            rc=proc.returncode
        if record['status']=='running':record['status']='completed' if rc==0 else 'runtime_error'
    except Exception as e:record.update(status='launcher_error',error=str(e).replace(key,'[REDACTED]'))
    finally:
        auth.unlink(missing_ok=True)
        for p in folder.rglob('*'):
            if p.is_file() and not p.is_symlink() and p.stat().st_size<50_000_000:
                b=p.read_bytes()
                if key.encode() in b:p.write_bytes(b.replace(key.encode(),b'[REDACTED]'))
    if not answer.exists():answer.write_text('')
    grading=official_grade(ROOT,ds,qid,answer);write(folder/'grading.json',grading)
    st,commands=stats(folder/'events.jsonl');st['estimated_cost_usd']=None
    write(folder/'commands.json',commands)
    record.update(returncode=rc,duration_s=time.monotonic()-start,answer=answer.read_text(),
                  grading_status=grading['status'],passed=grading['passed'] if record['status']=='completed' else None,
                  finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),**st)
    write(folder/'result.json',record);write(folder/'manifest.json',record)
    print('RESULT',ds,qid,record['status'],record['passed'],flush=True)
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
         'mongorestore','--uri','mongodb://'+urllib.parse.quote(str(sock/'mongodb-27017.sock'),safe=''),'--nsInclude',c['db_name']+'.*',str(root/f'query_{ds}'/c['dump_folder'])])
  print('DATABASES_LOADED',ds,flush=True)
 script="db.getSiblingDB('admin').createUser({user:'dab_readonly',pwd:'dab_readonly',roles:[{role:'readAnyDatabase',db:'admin'}]})"
 run(mb+['mongosh','mongodb://'+urllib.parse.quote(str(sock/'mongodb-27017.sock'),safe=''),'--quiet','--eval',script])
 run(mb+['mongod','--dbpath',str(mdata),'--shutdown'])
 run(mb+['mongod','--dbpath',str(mdata),'--unixSocketPrefix',str(sock),'--bind_ip','127.0.0.1','--port','27017','--auth','--fork','--logpath',str(rt/'mongo.log')])
 (pgdata/'pg_hba.conf').write_text('local all dab_readonly trust\nlocal all all reject\n')
 run(pgbase+['/usr/lib/postgresql/17/bin/pg_ctl','-D',str(pgdata),'reload'])
 time.sleep(1)
 return sock

def database_preflight(sockets):
    folder=OUT/'database-preflight'
    work,home,env=setup(folder,'stockindex',sockets)
    specs={}
    for ds in sorted({d for d,q in all_tasks(ROOT)}):
        cfg=yaml.safe_load((ROOT/f'query_{ds}/db_config.yaml').read_text())['db_clients']
        for c in cfg.values():
            if c['db_type'] in ('postgres','mongo'):
                specs[(c['db_type'],c['db_name'])]=True
    code="""import json,os,psycopg2,pymongo,socket,errno
checks=[]
for kind,name in SPECS:
    if kind=='postgres':
        c=psycopg2.connect(dbname=name,host=os.environ['PGHOST'],user='dab_readonly',connect_timeout=5)
        with c.cursor() as q:
            q.execute('SHOW default_transaction_read_only');assert q.fetchone()[0]=='on'
            q.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
            checks.append({'kind':kind,'database':name,'tables':q.fetchone()[0]})
        c.close()
    else:
        c=pymongo.MongoClient(os.environ['MONGO_URI'],serverSelectionTimeoutMS=5000)
        cols=c[name].list_collection_names();assert cols
        counts={col:c[name][col].count_documents({}) for col in cols}
        checks.append({'kind':kind,'database':name,'documents':counts})
        c.close()
try: psycopg2.connect(dbname='postgres',host=os.environ['PGHOST'],user='postgres',connect_timeout=5)
except psycopg2.OperationalError: pass
else: raise AssertionError('Administrative PostgreSQL role exposed')
c=pymongo.MongoClient(os.environ['MONGO_URI'],serverSelectionTimeoutMS=5000)
try:c['dab_permission_probe']['probe'].insert_one({'forbidden':True})
except pymongo.errors.OperationFailure as e:assert e.code==13
else:raise AssertionError('Mongo user can write')
try:socket.create_connection(('1.1.1.1',443),3)
except OSError as e:assert e.errno in (errno.EPERM,errno.EACCES,errno.ENETUNREACH)
else:raise AssertionError('External tool network allowed')
print(json.dumps(checks))
""".replace('SPECS',repr(list(specs)))
    r=subprocess.run([str(BIN),'-C',str(work),'sandbox','--',sys.executable,'-c',code],cwd=work,env=env,capture_output=True,text=True,timeout=120)
    result={'passed':r.returncode==0,'stdout':r.stdout,'stderr':r.stderr,'returncode':r.returncode,'inference_calls':0}
    write(OUT/'database-preflight.json',result)
    print('DATABASE_PREFLIGHT',json.dumps(result),flush=True)
    assert result['passed'],'Database access/read-only/network preflight failed'
    return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    assert os.getenv('SLURM_JOB_ID'),'Use a Slurm compute allocation'
    assert subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()==PIN
    pf=preflight()
    if not args.execute:return
    tasks=all_tasks(ROOT);assert len(tasks)==104
    write(OUT/'protocol.json',{'model':MODEL,'tasks':tasks,'trials_per_query':1,'upstream_commit':PIN,
          'condition':'description+hints','cli_version':'0.166.0','sandbox':'native bubblewrap with managed deny-by-default network proxy and filesystem-scoped Unix sockets','concurrency':6,'sandbox_revision':'unix-proxy-v2',
          'boundary':'Reconstructed Codex harness; not authors exact native driver. Original tasks and graders unchanged.',
          'cost_note':'Token usage retained. Billing estimate unavailable until pricing verified.'})
    pilot=one('stockindex',1,None,pf)
    assert pilot['status']=='completed' and pilot.get('tool_calls',0)>0 and pilot['grading_status']=='scored','Pilot failed; no full sweep'
    subprocess.run([sys.executable,'-m','dabbench.data','--upstream',str(ROOT),'--download'],cwd=PROJECT,check=True)
    manifest=ROOT.parent/'data-manifest.json'
    shutil.copyfile(manifest,OUT/'original-data-manifest.json')
    m=json.loads(manifest.read_text());assert len(m['queries'])==104 and all(x['verified'] for x in m['files'])
    runtime=Path(os.environ.get('SLURM_TMPDIR','/tmp'))/('dab-native-services-'+os.environ['SLURM_JOB_ID'])
    sockets=services(PROJECT,ROOT,runtime)
    database_preflight(sockets)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(one,d,q,sockets,pf) for d,q in tasks if (d,q)!=('stockindex',1)]
        for f in concurrent.futures.as_completed(futures):f.result()
    summary=generate(OUT)
    print('FINAL_SUMMARY',json.dumps(summary),flush=True)
    assert summary['complete'],'Incomplete: review infrastructure or grader failures'
    shutil.copytree(OUT/'reports',PROJECT/'results/terra-native-104x1',dirs_exist_ok=True)
    shutil.copyfile(OUT/'protocol.json',PROJECT/'results/terra-native-104x1/protocol.json')
    print('ALL_104_TRIALS_FINISHED',flush=True)

if __name__=='__main__':
    if '--submit' in sys.argv:
        script=PROJECT/'slurm/native104.sbatch'
        script.parent.mkdir(parents=True,exist_ok=True)
        (PROJECT/'strict-status').mkdir(exist_ok=True)
        script.write_text('#!/bin/bash\n#SBATCH --job-name=terra-native104\n#SBATCH --account=cse584f26_class\n#SBATCH --partition=standard\n#SBATCH --cpus-per-task=6\n#SBATCH --mem=32G\n#SBATCH --time=08:00:00\n#SBATCH --output=/home/minhyeok/llm-data-agent-benchmark/strict-status/native104-%j.log\nset -euo pipefail\nmodule load python/3.12.1 singularity\ncd /home/minhyeok/llm-data-agent-benchmark\nstrict/.venv/bin/python -u native104.py --execute\nstrict/.venv/bin/python -u finalize104.py\n')
        subprocess.run(['sbatch',str(script)],check=True)
    else:main()
