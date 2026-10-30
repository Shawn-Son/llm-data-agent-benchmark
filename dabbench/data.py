from __future__ import annotations
import argparse, json, subprocess, shutil
from pathlib import Path
from .core import UPSTREAM, digest, queries, write_json

def prepare(root, datasets, download=False):
    root = Path(root).resolve()
    commit = subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    if commit != UPSTREAM: raise ValueError(f'Expected upstream {UPSTREAM}, got {commit}')
    selected = set(datasets or [x[0] for x in queries(root)])
    manifest = {}
    for line in (root/'dataset_manifest.tsv').read_text().splitlines():
        if not line or line.startswith('#'): continue
        path, sha, size = line.split('\t'); manifest[path] = (sha,int(size))
    # Include all tracked database assets, not just the incomplete LFS manifest.
    tracked = subprocess.check_output(['git','-C',str(root),'ls-files'],text=True).splitlines()
    paths = sorted(set(manifest) | {p for p in tracked if '/query_dataset/' in p})
    rows = []
    for rel in paths:
        if rel.split('/')[0].removeprefix('query_') not in selected: continue
        p = root/rel
        expected = manifest.get(rel)
        pointer = p.exists() and p.stat().st_size < 1024 and p.read_bytes().startswith(b'version https://git-lfs.github.com/spec/v1')
        if pointer and not expected:
            fields=dict(line.split(' ',1) for line in p.read_text().splitlines())
            expected=(fields['oid'].split(':')[1], int(fields['size']))
        good = p.is_file() and not pointer
        if good and expected: good = p.stat().st_size==expected[1] and digest(p)==expected[0]
        if not good and download:
            from huggingface_hub import hf_hub_download
            hf_hub_download(repo_id='ruiyingm/DataAgentBench-data',repo_type='dataset',filename=rel,local_dir=root)
            good=p.is_file()
            if good and expected: good=p.stat().st_size==expected[1] and digest(p)==expected[0]
        rows.append(dict(path=rel,verified=good,sha256=digest(p) if good else None,
                         expected_sha256=expected[0] if expected else None,
                         size=p.stat().st_size if p.exists() else None))
    result=dict(upstream_commit=commit,datasets=sorted(selected),files=rows,
                queries=[dict(dataset=d,query=q,sha256=digest(p)) for d,q,p in queries(root) if d in selected])
    write_json(root.parent/'data-manifest.json',result)
    if not all(r['verified'] for r in rows): raise RuntimeError('Missing/corrupt data. Inspect data-manifest.json; use --download.')
    return result

def stage(root,dataset,dest):
    import yaml
    root=Path(root); dest=Path(dest); dest.mkdir(parents=True,exist_ok=True)
    ds=root/f'query_{dataset}'
    cfg=yaml.safe_load((ds/'db_config.yaml').read_text())['db_clients']
    connections={}
    for alias,c in cfg.items():
        kind=c['db_type']
        if kind in ('sqlite','duckdb'):
            src=(ds/c['db_path']).resolve()
            if not src.is_relative_to((ds/'query_dataset').resolve()): raise ValueError('Unexpected data path')
            dst=dest/src.name
            if dst.exists(): raise ValueError(f'Colliding database basename: {dst.name}')
            shutil.copyfile(src,dst); dst.chmod(0o444)
            connections[alias]=dict(db_type=kind,path='/data/'+dst.name)
        elif kind=='postgres':
            connections[alias]=dict(db_type=kind,dbname=c['db_name'],host='/sockets',user='dab_readonly')
        elif kind=='mongo':
            connections[alias]=dict(db_type=kind,dbname=c['db_name'],uri='mongodb://%2Fsockets%2Fmongodb-27017.sock')
        else: raise ValueError(kind)
    write_json(dest/'connections.json',connections)
    return connections

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--upstream',required=True);p.add_argument('--datasets',nargs='*');p.add_argument('--download',action='store_true')
    a=p.parse_args(); print(json.dumps(prepare(a.upstream,a.datasets,a.download),indent=2))
