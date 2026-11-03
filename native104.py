"""104-question DAB evaluation with an explicitly tested native bubblewrap sandbox.

Default (no options) reproduces the original 104x1 Codex/terra run layout.
--trial N writes an independent repeated sweep to <tag>-104x3/trialN.
--harness claude runs the same prompts, data, sockets and unchanged validators
through Claude Code (Claude Code's own bubblewrap sandbox for Bash, plus
permission deny rules for its built-in file tools).
"""
from pathlib import Path
import argparse, concurrent.futures, datetime, errno, json, os, shutil, signal, subprocess, sys, time, urllib.parse, yaml
PROJECT=Path(__file__).resolve().parent
sys.path.insert(0,str(PROJECT/'codex104'))
from run import all_tasks, prompt, official_grade, stats, services, write, digest, PIN
from report import generate
ROOT=Path('/home/minhyeok/dab-reproduction')
ARTIFACTS=Path('/home/minhyeok/dab-artifacts')
CODEX=Path('/home/minhyeok/.local/bin/codex')
CLAUDE=Path('/home/minhyeok/.local/bin/claude')
TOOLS=Path('/home/minhyeok/dab-tools/bin')  # user-space socat for Claude Code's Linux sandbox
KEYS={'codex':Path('/home/minhyeok/.config/dab/key'),'claude':Path('/home/minhyeok/.config/dab/anthropic_key')}
DEFAULT_MODEL={'codex':'gpt-5.6-terra','claude':'claude-haiku-5-5'}
TAGS={'codex':'terra-native','claude':'haiku-claude'}
REPEATS=3
HARNESS='codex';BIN=CODEX;MODEL='gpt-5.6-terra';TRIAL=0;BUDGET=None
OUT=ARTIFACTS/'terra-native-104x1'

def configure(harness='codex',model=None,trial=None,budget=None):
    """Select harness/model/trial. trial=None keeps the original 104x1 output directory."""
    global HARNESS,BIN,MODEL,TRIAL,OUT,BUDGET
    assert harness in DEFAULT_MODEL,harness
    HARNESS=harness;BIN=CODEX if harness=='codex' else CLAUDE
    MODEL=model or DEFAULT_MODEL[harness];BUDGET=budget
    TRIAL=0 if trial is None else int(trial)
    if trial is None:
        assert harness=='codex','Only the original Codex run uses the 104x1 layout'
        OUT=ARTIFACTS/'terra-native-104x1'
    else:
        assert 1<=TRIAL<=REPEATS,TRIAL
        OUT=ARTIFACTS/f'{TAGS[harness]}-104x{REPEATS}'/f'trial{TRIAL}'
    return OUT

def results_dir():
    return PROJECT/'results'/('terra-native-104x1' if OUT.name=='terra-native-104x1' else f'{OUT.parent.name}/{OUT.name}')

def protected_paths():
    """Answer-bearing paths the agent must never read: validators/ground truth, keys,
    archives, published results, logs, and every other run or trial directory."""
    paths=[ROOT/'query_*/query[0-9]*',Path('/home/minhyeok/.config/dab'),Path('/home/minhyeok/dab-archives'),
           ARTIFACTS/'terra-native-104x1',PROJECT/'results',PROJECT/'strict-status',PROJECT/'slurm',PROJECT/'.git',
           PROJECT/'README.md',PROJECT/'review-notes.json',PROJECT/'HARNESS_CORRECTION.md']
    for h,tag in TAGS.items():
        for k in range(1,REPEATS+1):
            d=ARTIFACTS/f'{tag}-104x{REPEATS}'/f'trial{k}'
            if d!=OUT:paths.append(d)
    return paths

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
    if HARNESS=='claude':return claude_setup(work,home,tmp,sockets)
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

def claude_setup(work,home,tmp,sockets):
    """Claude Code equivalent of the Codex profile: sandboxed Bash (no external network,
    all Unix sockets allowed so the DB sockets work, writes only in the task directory),
    deny rules for answer-bearing paths on both the sandbox and the built-in file tools,
    and the API key supplied by a helper outside the sandbox (never in the agent's env)."""
    deny=[str(p) for p in protected_paths()]
    settings={'apiKeyHelper':'cat '+str(KEYS['claude']),
              'permissions':{'allow':['Bash','Read','Glob','Grep'],
                             'deny':[f'{t}(/{p}/**)' for p in deny for t in ('Read','Edit')]+['WebFetch','WebSearch','Agent']},
              'sandbox':{'enabled':True,'failIfUnavailable':True,'autoAllowBashIfSandboxed':True,'allowUnsandboxedCommands':False,
                         'network':{'allowedDomains':[],'allowAllUnixSockets':True},
                         'filesystem':{'denyRead':deny,'allowWrite':[str(work)]}},
              'env':{'DISABLE_AUTOUPDATER':'1'}}
    write(home/'settings.json',settings)
    env=os.environ.copy()
    for k in ['ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN','OPENAI_API_KEY']:env.pop(k,None)
    env.update(CLAUDE_CONFIG_DIR=str(home),TMPDIR=str(tmp),PYTHONPATH=str(PROJECT/'strict/.venv/lib/python3.12/site-packages'),
               PATH=str(Path(sys.executable).parent)+':'+str(TOOLS)+':'+env.get('PATH',''),
               DISABLE_UPDATES='1',DISABLE_AUTOUPDATER='1',DISABLE_TELEMETRY='1',CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1',
               CLAUDE_CODE_DISABLE_WEB_FETCH='1',CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS='1',CLAUDE_CODE_DISABLE_BACKGROUND_TASKS='1',
               CLAUDE_CODE_DISABLE_OFFICIAL_MARKETPLACE_AUTOINSTALL='1',NO_PROXY='',no_proxy='')
    if sockets:
        uri='mongodb://dab_readonly:dab_readonly@'+urllib.parse.quote(str(sockets/'mongodb-27017.sock'),safe='')+'/?authSource=admin'
        env.update(PGHOST=str(sockets),PGUSER='dab_readonly',PGPORT='5432',MONGO_URI=uri)
        write(work/'connections.json',{'postgres':{'host':str(sockets),'user':'dab_readonly','port':5432},'mongodb':{'uri':uri}})
    return work,home,env

def agent_command(work,home,answer):
    if HARNESS=='codex':
        return [str(BIN),'-C',str(work),'--ask-for-approval','never','exec','--json','--skip-git-repo-check',
                '--model',MODEL,'--output-last-message',str(answer),'-']
    cmd=[str(BIN),'-p','--bare','--model',MODEL,'--output-format','stream-json','--verbose',
         '--settings',str(home/'settings.json'),'--permission-mode','acceptEdits',
         '--tools','Bash,Read,Edit,Write,Glob,Grep','--disallowedTools','WebFetch,WebSearch,Agent','--no-session-persistence']
    if BUDGET:cmd+=['--max-budget-usd',str(BUDGET)]
    return cmd

def claude_final(events):
    """Final answer text and terminal status from Claude Code's stream-json result event."""
    last=None
    for line in Path(events).read_text(errors='replace').splitlines():
        try:e=json.loads(line)
        except ValueError:continue
        if e.get('type')=='result':last=e
    return last

def tool_outputs(events,name=None):
    """Actual tool_result texts (not model prose), optionally for one tool name."""
    names={};outs=[]
    for line in Path(events).read_text(errors='replace').splitlines():
        try:e=json.loads(line)
        except ValueError:continue
        for b in (e.get('message') or {}).get('content') or []:
            if not isinstance(b,dict):continue
            if b.get('type')=='tool_use':names[b.get('id')]=(b.get('name'),b.get('input'))
            if b.get('type')=='tool_result':
                c=b.get('content');text=c if isinstance(c,str) else '\n'.join(x.get('text','') for x in c or [] if isinstance(x,dict))
                n,i=names.get(b.get('tool_use_id'),(None,None))
                if name is None or n==name:outs.append({'tool':n,'input':i,'is_error':bool(b.get('is_error')),'text':text})
    return outs

def claude_preflight(folder,work,home,env,code,marker,blocked):
    """Claude Code has no 'sandbox --' subcommand, so the identical check script is run
    through one real session's Bash tool; pass/fail is read from the tool_result itself,
    never from model prose. The built-in Read tool must also be denied on a protected path."""
    (work/'preflight_check.py').write_text(code)
    ask=('This is an environment test. Run exactly `python preflight_check.py` with the Bash tool and nothing else. '
         f'Then try to read the file {blocked} with the Read tool. Finally reply with the Bash output only.')
    events=folder/'events.jsonl'
    with events.open('w') as out,(folder/'stderr.log').open('w') as err:
        r=subprocess.run([str(BIN),'-p',ask]+agent_command(work,home,None)[2:],cwd=work,env=env,stdout=out,stderr=err,text=True,timeout=600)
    bash=tool_outputs(events,'Bash');reads=tool_outputs(events,'Read');final=claude_final(events) or {}
    read_denied=bool(reads) and all(x['is_error'] for x in reads) or any(d.get('tool_name')=='Read' for d in final.get('permission_denials') or [])
    bash_ok=any(marker in x['text'] and not x['is_error'] for x in bash)
    return {'passed':r.returncode==0 and bash_ok and read_denied,'returncode':r.returncode,'bash_outputs':[x['text'][-3000:] for x in bash],
            'read_tool_denied':read_denied,'read_attempts':len(reads),'permission_denials':final.get('permission_denials'),
            'stderr':(folder/'stderr.log').read_text()[-3000:],'inference_calls':1,'total_cost_usd':final.get('total_cost_usd')}

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
""".replace('BLOCKED',repr([str(blocked),str(outside)]+[str(k) for k in KEYS.values() if k.exists()]+
                             [str(ARTIFACTS/'terra-native-104x1/preflight-latest.json')])).replace('OUTSIDE',repr(str(outside)))
    if HARNESS=='claude':
        result=claude_preflight(folder,work,home,env,code,'NATIVE_ISOLATION_AND_NETWORK_OK',blocked)
        result['passed']=result['passed'] and outside.read_text()=='private-sentinel'
        result.update(binary_sha256=digest(BIN.resolve()),version=subprocess.check_output([str(BIN),'--version'],text=True,env=env).strip(),
                      config=(home/'settings.json').read_text())
    else:
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
    cmd=agent_command(work,home,answer)
    record={'model':MODEL,'dataset':ds,'query':qid,'trial':TRIAL,'condition':'description+hints',
            'upstream_commit':PIN,'harness':pf['version'] if HARNESS=='claude' else 'native Codex CLI 0.166.0','harness_reconstruction':True,
            'sandbox_revision':'claude-code-bwrap-v1' if HARNESS=='claude' else 'unix-proxy-v2',
            'binary_sha256':pf['binary_sha256'],'prompt_sha256':digest(folder/'prompt.txt'),
            'status':'running','passed':None,'slurm_job_id':os.getenv('SLURM_JOB_ID'),
            'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    write(folder/'manifest.json',record)
    key=KEYS[HARNESS].read_text().strip()
    auth=home/'auth.json'
    if HARNESS=='codex':auth.write_text(json.dumps({'auth_mode':'apikey','OPENAI_API_KEY':key}));auth.chmod(0o600)
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
        if HARNESS=='claude':
            final=claude_final(folder/'events.jsonl')
            if final and isinstance(final.get('result'),str):answer.write_text(final['result'])
            # A run stopped by a client-side limit is a completed model attempt; an API failure is infrastructure.
            if record['status']=='running' and final and final.get('subtype') in ('error_max_turns','error_max_budget_usd'):
                record['status']='completed';record['terminal_reason']=final.get('subtype')
            elif record['status']=='running' and (final is None or (final.get('is_error') and final.get('subtype')=='success')):
                record['status']='runtime_error'
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
    st,commands=stats(folder/'events.jsonl')
    if HARNESS=='codex':st['estimated_cost_usd']=None  # Claude keeps Claude Code's own client-side estimate
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
print('DATABASE_PREFLIGHT_OK')
""".replace('SPECS',repr(list(specs)))
    if HARNESS=='claude':
        result=claude_preflight(folder,work,home,env,code,'DATABASE_PREFLIGHT_OK',ROOT/'query_stockindex/query1/validate.py')
    else:
        r=subprocess.run([str(BIN),'-C',str(work),'sandbox','--',sys.executable,'-c',code],cwd=work,env=env,capture_output=True,text=True,timeout=120)
        result={'passed':r.returncode==0,'stdout':r.stdout,'stderr':r.stderr,'returncode':r.returncode,'inference_calls':0}
    write(OUT/'database-preflight.json',result)
    print('DATABASE_PREFLIGHT',json.dumps(result),flush=True)
    assert result['passed'],'Database access/read-only/network preflight failed'
    return result

def arguments(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument('--execute',action='store_true',help='run the full sweep after preflight')
    p.add_argument('--pilot',action='store_true',help='preflight plus the stockindex q1 pilot only')
    p.add_argument('--submit',action='store_true',help='write and submit the Slurm job for these options')
    p.add_argument('--harness',choices=sorted(DEFAULT_MODEL),default='codex')
    p.add_argument('--model',default=None)
    p.add_argument('--trial',type=int,default=None,help=f'repeated sweep 1..{REPEATS}; omit for the original 104x1 layout')
    p.add_argument('--budget',type=float,default=None,help='Claude Code per-question --max-budget-usd')
    p.add_argument('--after',default=None,help='Slurm job id this submission waits for (afterany)')
    return p.parse_args(argv)

def main(args):
    configure(args.harness,args.model,args.trial,args.budget)
    assert os.getenv('SLURM_JOB_ID'),'Use a Slurm compute allocation'
    assert subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()==PIN
    pf=preflight()
    if not (args.execute or args.pilot):return
    tasks=all_tasks(ROOT);assert len(tasks)==104
    version=pf['version'] if HARNESS=='claude' else '0.166.0'
    write(OUT/'protocol.json',{'model':MODEL,'harness':HARNESS,'trial':TRIAL,'repeats':REPEATS if args.trial else 1,
          'tasks':tasks,'trials_per_query':1,'upstream_commit':PIN,'condition':'description+hints','cli_version':version,
          'sandbox':('Claude Code bubblewrap sandbox for Bash: no external domains, all Unix sockets allowed, writes only in the task directory; '
                     'deny rules on answer-bearing paths for both the sandbox and built-in file tools; key via apiKeyHelper outside the sandbox')
                    if HARNESS=='claude' else 'native bubblewrap with managed deny-by-default network proxy and filesystem-scoped Unix sockets',
          'concurrency':6,'sandbox_revision':'claude-code-bwrap-v1' if HARNESS=='claude' else 'unix-proxy-v2',
          'max_budget_usd_per_question':BUDGET,
          'boundary':('Claude Code harness (as the paper used for Claude models); not the authors exact driver. ' if HARNESS=='claude' else
                      'Reconstructed Codex harness; not authors exact native driver. ')+'Original tasks and graders unchanged.',
          'cost_note':'Token usage retained. Claude Code total_cost_usd is a client-side estimate, not billing.' if HARNESS=='claude' else
                      'Token usage retained. Billing estimate unavailable until pricing verified.'})
    pilot=one('stockindex',1,None,pf)
    assert pilot['status']=='completed' and pilot.get('tool_calls',0)>0 and pilot['grading_status']=='scored','Pilot failed; no full sweep'
    print('PILOT',json.dumps({k:pilot.get(k) for k in ['passed','duration_s','tool_calls','input_tokens','cached_input_tokens','output_tokens','estimated_cost_usd']}),flush=True)
    if args.pilot:return
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
    dest=results_dir();shutil.copytree(OUT/'reports',dest,dirs_exist_ok=True)
    shutil.copyfile(OUT/'protocol.json',dest/'protocol.json')
    print('ALL_104_TRIALS_FINISHED',flush=True)

def submit(args):
    """Write one Slurm script per harness/model/trial; --pilot submits only preflight+pilot."""
    configure(args.harness,args.model,args.trial,args.budget)
    opts=f'--harness {HARNESS} --model {MODEL}'+(f' --trial {TRIAL}' if args.trial else '')+(f' --budget {BUDGET}' if BUDGET else '')
    name=(f'{TAGS[HARNESS]}-t{TRIAL}' if args.trial else 'terra-native104')+('-pilot' if args.pilot else '')
    script=PROJECT/'slurm'/(name+'.sbatch');script.parent.mkdir(parents=True,exist_ok=True)
    (PROJECT/'strict-status').mkdir(exist_ok=True)
    body=('#!/bin/bash\n'f'#SBATCH --job-name={name}\n#SBATCH --account=cse584f26_class\n#SBATCH --partition=standard\n'
          '#SBATCH --cpus-per-task=6\n#SBATCH --mem=32G\n'f'#SBATCH --time={"01:00:00" if args.pilot else "08:00:00"}\n'
          f'#SBATCH --output=/home/minhyeok/llm-data-agent-benchmark/strict-status/{name}-%j.log\n'
          'set -euo pipefail\nmodule load python/3.12.1 singularity\ncd /home/minhyeok/llm-data-agent-benchmark\n'
          f'strict/.venv/bin/python -u native104.py {"--pilot" if args.pilot else "--execute"} {opts}\n')
    if not args.pilot:body+=f'strict/.venv/bin/python -u finalize104.py {opts}\n'
    script.write_text(body)
    cmd=['sbatch','--parsable']+([f'--dependency=afterany:{args.after}'] if args.after else [])+[str(script)]
    job=subprocess.run(cmd,check=True,capture_output=True,text=True).stdout.strip()
    print('SUBMITTED',name,job,flush=True)

if __name__=='__main__':
    a=arguments()
    submit(a) if a.submit else main(a)
