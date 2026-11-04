"""Shared helpers for the offline experiments (no API key needed)."""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DAB = Path(os.environ.get('DAB_ROOT', Path.home() / 'DataAgentBench'))
RESULTS = ROOT / 'experiments' / 'results'
RESULTS.mkdir(parents=True, exist_ok=True)


def dataset(name: str) -> Path:
    p = DAB / f'query_{name}' / 'query_dataset'
    if not p.exists(): raise SystemExit(f'missing {p}: clone ucbepic/DataAgentBench at the pinned commit and run download.sh (set DAB_ROOT)')
    return p


def save(name: str, obj, md: str = ''):
    (RESULTS / f'{name}.json').write_text(json.dumps(obj, indent=2, default=str) + '\n')
    if md: (RESULTS / f'{name}.md').write_text(md)
    print(f'wrote {RESULTS / name}.json')


class Timer:
    def __init__(self): self.t = time.time()
    def __call__(self): return round(time.time() - self.t, 1)
