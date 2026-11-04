"""Load selected tables of a PostgreSQL dump into sqlite, for offline experiments on the DAB
PostgreSQL datasets without a server. Handles COPY ... FROM stdin blocks (text or CSV format,
as pg_dump writes them) and plain CREATE TABLE / INSERT INTO dumps."""
from __future__ import annotations
import csv, io, re, sqlite3
from typing import Dict, List, Optional, Sequence

_COPY = re.compile(r'^COPY\s+(?:"?[\w]+"?\.)?"?(?P<table>[\w]+)"?\s*\((?P<cols>.*?)\)\s+FROM\s+stdin(?P<opts>.*?);\s*$', re.I)
_CREATE = re.compile(r'^CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:"?[\w]+"?\.)?"?(?P<table>[\w]+)"?', re.I)
_INSERT = re.compile(r'^INSERT\s+INTO\s+(?:"?[\w]+"?\.)?"?(?P<table>[\w]+)"?', re.I)


def _copy_options(opts: str) -> Dict[str, str]:
    o = {'format': 'text', 'delimiter': '\t', 'null': '\\N'}
    m = re.search(r'FORMAT\s+(\w+)', opts, re.I)
    if m: o['format'] = m.group(1).lower()
    m = re.search(r"DELIMITER\s+E?'(.*?)'", opts, re.I)
    if m: o['delimiter'] = m.group(1).encode().decode('unicode_escape')
    m = re.search(r"NULL\s+'(.*?)'", opts, re.I)
    if m: o['null'] = m.group(1)
    return o


_ESC = {'t': '\t', 'n': '\n', 'r': '\r', '\\': '\\', 'b': '\b', 'f': '\f', 'v': '\v'}


def _unescape(v: str) -> str:
    """COPY text-format escapes, decoded in one pass so that a literal backslash followed by
    't' stays a backslash plus 't'."""
    if '\\' not in v: return v
    return re.sub(r'\\(.)', lambda m: _ESC.get(m.group(1), m.group(1)), v)


def _strip_schema(stmt: str) -> str:
    return re.sub(r'\b(?:public|main)\.', '', stmt)


def load_pgdump(path: str, tables: Optional[Sequence[str]] = None, sqlite_path: str = ':memory:',
                max_rows: Optional[int] = None) -> sqlite3.Connection:
    """Stream the dump once. COPY tables are created with TEXT columns; CREATE TABLE / INSERT
    statements for the requested tables are executed as written (sqlite accepts the dump syntax)."""
    want = set(tables) if tables else None
    con = sqlite3.connect(sqlite_path)
    cur = con.cursor(); cur.execute('PRAGMA journal_mode=OFF'); cur.execute('PRAGMA synchronous=OFF')
    current = None; cols: List[str] = []; opts: Dict[str, str] = {}; n = 0; batch: List[tuple] = []
    stmt: List[str] = []; stmt_table: Optional[str] = None; keep = False
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            if current is not None:                       # inside a COPY block
                if line.startswith('\\.'):
                    if batch: cur.executemany(f'INSERT INTO "{current}" VALUES (' + ','.join('?' * len(cols)) + ')', batch); batch = []
                    current = None; continue
                if max_rows is not None and n >= max_rows: continue
                if opts['format'] == 'csv':
                    vals = next(csv.reader(io.StringIO(line.rstrip('\n')), delimiter=opts['delimiter'], quotechar='"'))
                    vals = [None if v == opts['null'] else v for v in vals]
                else:
                    vals = [None if v == opts['null'] else _unescape(v) for v in line.rstrip('\n').split(opts['delimiter'])]
                if len(vals) != len(cols): continue
                batch.append(tuple(vals)); n += 1
                if len(batch) >= 5000:
                    cur.executemany(f'INSERT INTO "{current}" VALUES (' + ','.join('?' * len(cols)) + ')', batch); batch = []
                continue
            if stmt:                                       # inside a multi-line statement
                stmt.append(line)
                if line.rstrip().endswith(';'):
                    if keep: cur.execute(_strip_schema(''.join(stmt)))
                    stmt = []
                continue
            m = _COPY.match(line)
            if m:
                if want is None or m.group('table') in want:
                    current = m.group('table'); cols = [c.strip().strip('"') for c in m.group('cols').split(',')]
                    opts = _copy_options(m.group('opts') or ''); n = 0
                    if not cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (current,)).fetchone():
                        cur.execute(f'CREATE TABLE "{current}" (' + ', '.join(f'"{c}" TEXT' for c in cols) + ')')
                else:
                    current = None
                    for line2 in f:                         # skip the block
                        if line2.startswith('\\.'): break
                continue
            m = _CREATE.match(line) or _INSERT.match(line)
            if m:
                keep = want is None or m.group('table') in want
                if line.rstrip().endswith(';'):
                    if keep: cur.execute(_strip_schema(line))
                else: stmt = [line]
    con.commit()
    return con


def list_tables(path: str) -> Dict[str, List[str]]:
    """Tables with their column lists (COPY headers), or just names for INSERT/CREATE dumps."""
    out: Dict[str, List[str]] = {}
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            m = _COPY.match(line)
            if m: out[m.group('table')] = [c.strip().strip('"') for c in m.group('cols').split(',')]; continue
            m = _CREATE.match(line)
            if m: out.setdefault(m.group('table'), [])
    return out
