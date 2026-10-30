"""Validate the isolated Codex runtime without changing upstream code."""
from pathlib import Path
import argparse,json,os,subprocess,hashlib,shutil

def digest(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()

def invocation(project,jobroot,home,work,extra_binds=(),extra_env=None):
 project=Path(project);home=Path(home);work=Path(work)
 binary=Path('/home/minhyeok/.local/bin/codex114').resolve()
 deps=project/'strict/.venv/lib/python3.12/site-packages'
 env={'PYTHONPATH':'/opt/deps','TMPDIR':'/tmp','XDG_RUNTIME_DIR':'/tmp/codex-runtime',
      'CODEX_HOME':'/home/agent/.codex','NO_PROXY':'','no_proxy':'',
      'HTTPS_PROXY':os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY',''),
      'HTTP_PROXY':os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY','')}
 env.update(extra_env or {})
 argv=['singularity','exec','--userns','--tmp-sandbox','--containall','--cleanenv','--no-mount','hostfs,cwd,bind-paths',
       '--home',str(home)+':/home/agent','--pwd','/work','--bind',str(work)+':/work',
       '--bind',str(binary)+':/usr/local/bin/codex:ro','--bind',str(deps)+':/opt/deps:ro']
 argv+=['--bind','/dev/full:/dev/full']
 resources=binary.parent/'codex-resources'
 if resources.is_dir():argv+=['--bind',str(resources)+':/usr/local/bin/codex-resources:ro']
 bwrap=project/'runtime/bwrap-0.166.0'
 if bwrap.is_file():argv+=['--bind',str(bwrap)+':/usr/local/bin/codex-resources/bwrap:ro']
 for b in extra_binds:argv+=['--bind',str(b)]
 for k,v in env.items():argv+=['--env',k+'='+v]
 argv+=[str(project/'runtime/strict-python312.sif')]
 return argv

def client_config(home):
 p=Path(home)/'.codex';p.mkdir(parents=True,mode=0o700,exist_ok=True)
 (p/'config.toml').write_text('model_provider = "toolkit"\nmodel = "gpt-5.6-terra"\nweb_search = "disabled"\n[model_providers.toolkit]\nname = "UM GPT Toolkit"\nbase_url = "https://api.toolkit.umgpt.umich.edu/v1"\nwire_api = "responses"\nrequires_openai_auth = true\n')
 with (p/'config.toml').open('a') as f:
  f.write('\n[permissions.dab.filesystem]\n"/" = "read"\n"/work" = "write"\n"/tmp" = "write"\n"/opt/deps" = "read"\n"/sockets" = "read"\n"/home/agent" = "read"\n[permissions.dab.network]\nenabled = false\n')
 original=(p/'config.toml').read_text()
 (p/'config.toml').write_text('default_permissions = "dab"\n'+original)
 return p

def check(project,out):
 project=Path(project);out=Path(out);out.mkdir(parents=True,exist_ok=False)
 home=out/'home';home.mkdir(mode=0o700);work=out/'work';work.mkdir();client_config(home)
 base=invocation(project,out,home,work)
 checks=[]
 tests=[('imports_and_filesystem',['python','-c',"import os,sqlite3,duckdb,pandas,pyarrow,psycopg2,pymongo; assert not os.path.exists('/home/minhyeok/dab-reproduction/run_agent.py');print('ISOLATION_OK')"]),
        ('codex_version',['codex','--version']),
        ('codex_sandbox',['codex','sandbox','linux','--','/bin/echo','CODEX_SANDBOX_OK']),
        ('sandbox_network_block',['codex','sandbox','linux','--','python','-c',"import socket;socket.create_connection(('1.1.1.1',443),3)"])]
 for name,cmd in tests:
  print('TEST',name,flush=True)
  try:
   r=subprocess.run(base+cmd,capture_output=True,text=True,timeout=45)
   entry={'name':name,'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr}
  except subprocess.TimeoutExpired:entry={'name':name,'returncode':None,'error':'timeout'}
  checks.append(entry);print(json.dumps(entry),flush=True)
  (out/'checks.json').write_text(json.dumps(checks,indent=2))
  if name!='sandbox_network_block' and entry['returncode']!=0:raise RuntimeError('Preflight failed: '+name)
  if name=='sandbox_network_block':
   text=(entry.get('stdout','')+entry.get('stderr',''))
   if entry['returncode'] in (0,None) or not any(s in text for s in ['Operation not permitted','PermissionError','Network is unreachable']):
    raise RuntimeError('Could not verify network sandbox')
 result={'passed':True,'image_sha256':digest(project/'runtime/strict-python312.sif'),
         'codex_sha256':digest(Path('/home/minhyeok/.local/bin/codex114').resolve()),'bwrap_sha256':digest(project/'runtime/bwrap-0.166.0'),'checks':checks,'inference_calls':0}
 (out/'preflight.json').write_text(json.dumps(result,indent=2));return result

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--project',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();check(a.project,a.out)
