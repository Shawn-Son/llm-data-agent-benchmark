"""Read-only access to one DataAgentBench dataset from its files (no database servers needed).

The harness loads PostgreSQL dumps and MongoDB dumps into servers for the agent; the
preprocessing and verification steps here read the same files directly:
  sqlite / duckdb  -> the database file (read-only)
  postgres         -> the pg_dump .sql file, streamed into an in-memory sqlite database
  mongo            -> the mongodump .bson files, decoded with pymongo's bson module
"""
from __future__ import annotations
import json, sqlite3
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

import yaml


class DABDataset:
    def __init__(self, root, name: str):
        self.root = Path(root); self.name = name
        self.dir = self.root / f'query_{name}'
        cfg = yaml.safe_load((self.dir / 'db_config.yaml').read_text())['db_clients']
        self.clients: Dict[str, Dict[str, Any]] = {k: dict(v) for k, v in cfg.items()}
        self._pg: Dict[str, sqlite3.Connection] = {}

    def kind(self, alias: str) -> str: return self.clients[alias]['db_type']

    def path(self, alias: str) -> Path:
        c = self.clients[alias]
        rel = c.get('db_path') or c.get('sql_file') or c.get('dump_folder')
        return self.dir / rel

    # ---------------------------------------------------------------- SQL databases
    def _pg_con(self, alias: str) -> sqlite3.Connection:
        if alias not in self._pg:
            from .util.pgdump import load_pgdump
            self._pg[alias] = load_pgdump(str(self.path(alias)))
        return self._pg[alias]

    def query(self, alias: str, sql: str) -> List[tuple]:
        """Run a read-only query against an sqlite / duckdb / postgres-dump database."""
        k = self.kind(alias)
        if k == 'sqlite':
            con = sqlite3.connect(f'file:{self.path(alias)}?mode=ro', uri=True)
            try: return con.execute(sql).fetchall()
            finally: con.close()
        if k == 'duckdb':
            import duckdb
            con = duckdb.connect(str(self.path(alias)), read_only=True)
            try: return con.execute(sql).fetchall()
            finally: con.close()
        if k == 'postgres':
            return self._pg_con(alias).execute(sql).fetchall()
        raise ValueError(f'{alias} is a {k} database; use documents()')

    def column(self, alias: str, table: str, column: str, distinct: bool = True) -> List[Any]:
        """Values of one column (or one top-level / dotted document field for mongo)."""
        if self.kind(alias) == 'mongo':
            out, seen = [], set()
            for doc in self.documents(alias, table):
                v = _get(doc, column)
                if distinct:
                    if v is None or v in seen: continue
                    seen.add(v)
                out.append(v)
            return out
        q = f'SELECT {"DISTINCT " if distinct else ""}"{column}" FROM "{table}"'
        if distinct: q += f' WHERE "{column}" IS NOT NULL'
        return [r[0] for r in self.query(alias, q)]

    def rows(self, alias: str, table: str, columns: Sequence[str]) -> List[Dict[str, Any]]:
        if self.kind(alias) == 'mongo':
            return [{c: _get(d, c) for c in columns} for d in self.documents(alias, table)]
        cols = ', '.join(f'"{c}"' for c in columns)
        return [dict(zip(columns, r)) for r in self.query(alias, f'SELECT {cols} FROM "{table}"')]

    # ---------------------------------------------------------------- MongoDB dumps
    def documents(self, alias: str, collection: str) -> Iterator[Dict[str, Any]]:
        import bson
        folder = self.path(alias)
        files = sorted(folder.rglob(f'{collection}.bson'))
        if not files: raise FileNotFoundError(f'no {collection}.bson under {folder}')
        with open(files[0], 'rb') as f:
            for doc in bson.decode_file_iter(f): yield doc

    # ---------------------------------------------------------------- schemas for SQL verification
    def sql_schemas(self, sample_rows: int = 2) -> Dict[str, Any]:
        """{alias: Schema} for every SQL database (sqlite, duckdb, postgres dump); mongo is skipped."""
        from .sqlverify.schema import schema_from_sqlite, schema_from_duckdb, schema_from_ddl, Schema, Table, Column
        out = {}
        for alias, c in self.clients.items():
            k = c['db_type']
            if k == 'sqlite': out[alias] = schema_from_sqlite(str(self.path(alias)), sample_rows=sample_rows)
            elif k == 'duckdb': out[alias] = schema_from_duckdb(str(self.path(alias)), sample_rows=sample_rows)
            elif k == 'postgres':
                con = self._pg_con(alias)
                sc = Schema(dialect='postgres')
                for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                    cols = [Column(r[1], r[2] or 'TEXT') for r in con.execute(f'PRAGMA table_info("{t}")')]
                    samples = []
                    if sample_rows:
                        cur = con.execute(f'SELECT * FROM "{t}" LIMIT {int(sample_rows)}')
                        keys = [d[0] for d in cur.description]
                        samples = [dict(zip(keys, (str(v)[:80] if v is not None else None for v in row))) for row in cur.fetchall()]
                    sc.add(Table(t, cols, samples))
                out[alias] = sc
        return out


def _get(doc: Dict[str, Any], dotted: str) -> Any:
    cur: Any = doc
    for part in dotted.split('.'):
        if isinstance(cur, dict): cur = cur.get(part)
        else: return None
    if cur is not None and not isinstance(cur, (str, int, float, bool)):
        cur = json.dumps(cur, default=str, ensure_ascii=False)
    return cur
