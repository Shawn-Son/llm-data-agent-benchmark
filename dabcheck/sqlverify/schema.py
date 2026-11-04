"""Database schema objects and loaders (sqlite, duckdb, DDL / pg_dump text)."""
from __future__ import annotations
import json, re, sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


@dataclass
class Column:
    name: str
    type: str = ''
    description: str = ''


@dataclass
class Table:
    name: str
    columns: List[Column] = field(default_factory=list)
    samples: List[Dict[str, Any]] = field(default_factory=list)
    description: str = ''

    def column_names(self) -> List[str]: return [c.name for c in self.columns]


@dataclass
class Schema:
    tables: Dict[str, Table] = field(default_factory=dict)
    dialect: str = 'sqlite'
    notes: str = ''

    def add(self, table: Table): self.tables[table.name] = table; return self

    def sqlite_type(self, t: str) -> str:
        t = (t or '').lower()
        if any(k in t for k in ('int', 'serial', 'bigint', 'smallint')): return 'INTEGER'
        if any(k in t for k in ('real', 'double', 'float', 'numeric', 'decimal')): return 'REAL'
        return 'TEXT'

    def ddl_sqlite(self) -> List[str]:
        out = []
        for t in self.tables.values():
            cols = ', '.join(f'"{c.name}" {self.sqlite_type(c.type)}' for c in t.columns)
            out.append(f'CREATE TABLE "{t.name}" ({cols})')
        return out


def render_schema(schema: Schema, max_samples: int = 2, max_tables: int = 40) -> str:
    """Compact text for prompts: table, columns with types, a couple of sample rows."""
    lines = [f'Dialect: {schema.dialect}']
    if schema.notes: lines.append('Notes: ' + schema.notes)
    for t in list(schema.tables.values())[:max_tables]:
        lines.append(f'TABLE {t.name}' + (f' -- {t.description}' if t.description else ''))
        for c in t.columns:
            lines.append(f'  {c.name} {c.type}'.rstrip() + (f' -- {c.description}' if c.description else ''))
        for s in t.samples[:max_samples]:
            lines.append('  sample: ' + json.dumps(s, ensure_ascii=False, default=str)[:300])
    return '\n'.join(lines)


def schema_from_sqlite(path: str, sample_rows: int = 2, tables: Optional[Sequence[str]] = None) -> Schema:
    con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        sc = Schema(dialect='sqlite')
        for n in names:
            if tables and n not in tables: continue
            cols = [Column(r[1], r[2] or '') for r in con.execute(f'PRAGMA table_info("{n}")')]
            samples = []
            if sample_rows:
                cur = con.execute(f'SELECT * FROM "{n}" LIMIT {int(sample_rows)}')
                keys = [d[0] for d in cur.description]
                samples = [dict(zip(keys, (str(v)[:80] if v is not None else None for v in row))) for row in cur.fetchall()]
            sc.add(Table(n, cols, samples))
        return sc
    finally: con.close()


def schema_from_duckdb(path: str, sample_rows: int = 2, tables: Optional[Sequence[str]] = None) -> Schema:
    import duckdb
    con = duckdb.connect(path, read_only=True)
    try:
        names = [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()]
        sc = Schema(dialect='duckdb')
        for n in names:
            if tables and n not in tables: continue
            cols = [Column(r[0], r[1]) for r in con.execute(
                f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name='{n}' ORDER BY ordinal_position").fetchall()]
            samples = []
            if sample_rows:
                cur = con.execute(f'SELECT * FROM "{n}" LIMIT {int(sample_rows)}')
                keys = [d[0] for d in cur.description]
                samples = [dict(zip(keys, (str(v)[:80] if v is not None else None for v in row))) for row in cur.fetchall()]
            sc.add(Table(n, cols, samples))
        return sc
    finally: con.close()


_CREATE = re.compile(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:"?[\w]+"?\.)?"?(?P<name>[\w]+)"?\s*\((?P<body>.*?)\)\s*;', re.I | re.S)


def schema_from_ddl(text: str, dialect: str = 'postgres') -> Schema:
    """CREATE TABLE statements (hand-written or a pg_dump header) -> Schema. sqlglot is used when
    available; a regex fallback handles plain column lists."""
    sc = Schema(dialect=dialect)
    # drop pg_dump COPY data blocks and psql meta-commands, which are not SQL
    text = re.sub(r'^COPY\s.*?FROM\s+stdin;.*?^\\\.\s*$', '', text, flags=re.S | re.M | re.I)
    text = re.sub(r'^\\.*$', '', text, flags=re.M)
    try:
        import sqlglot
        from sqlglot import exp
        for stmt in sqlglot.parse(text, read=dialect, error_level=sqlglot.ErrorLevel.IGNORE):
            if not isinstance(stmt, exp.Create) or stmt.args.get('kind', '').upper() != 'TABLE': continue
            name = stmt.this.this.name if isinstance(stmt.this, exp.Schema) else stmt.this.name
            cols = []
            schema_node = stmt.this if isinstance(stmt.this, exp.Schema) else None
            for e in (schema_node.expressions if schema_node else []):
                if isinstance(e, exp.ColumnDef):
                    cols.append(Column(e.this.name, e.args['kind'].sql(dialect=dialect) if e.args.get('kind') else ''))
            if name and cols: sc.add(Table(name, cols))
    except Exception: pass
    for m in _CREATE.finditer(text):   # regex pass adds whatever sqlglot skipped
        if m.group('name') in sc.tables: continue
        cols = []
        for part in re.split(r',\s*(?![^()]*\))', m.group('body')):
            part = part.strip()
            if not part or re.match(r'(PRIMARY|FOREIGN|UNIQUE|CONSTRAINT|CHECK|KEY)\b', part, re.I): continue
            mm = re.match(r'"?(?P<col>[\w]+)"?\s+(?P<type>[\w\s\(\),]*)', part)
            if mm: cols.append(Column(mm.group('col'), mm.group('type').strip()))
        if cols: sc.add(Table(m.group('name'), cols))
    return sc
