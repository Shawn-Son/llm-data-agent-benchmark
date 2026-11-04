"""Command-line entry points: python -m dabcheck.cli <command> ...

  audit-join   LLM-free identifier-join audit between two key columns
  extract      code-first extraction with a parse-coverage report (LLM optional)
  verify-sql   verify a SQL query against a question with round-trip / synthetic execution / cohort cards
  fdj          FDJ join between two tables with an LLM labeller (requires an API key)
"""
from __future__ import annotations
import argparse, csv, json, sqlite3, sys
from pathlib import Path
from typing import Any, List, Optional


def _read_column(source: str, column: str, table: Optional[str] = None, limit: Optional[int] = None) -> List[Any]:
    """source: a CSV path, or 'sqlite:/path.db' / 'duckdb:/path.db' with --table."""
    if source.startswith('sqlite:'):
        con = sqlite3.connect(f'file:{source[7:]}?mode=ro', uri=True)
        q = f'SELECT "{column}" FROM "{table}"' + (f' LIMIT {int(limit)}' if limit else '')
        return [r[0] for r in con.execute(q)]
    if source.startswith('duckdb:'):
        import duckdb
        con = duckdb.connect(source[7:], read_only=True)
        q = f'SELECT "{column}" FROM "{table}"' + (f' LIMIT {int(limit)}' if limit else '')
        return [r[0] for r in con.execute(q).fetchall()]
    with open(source, newline='') as f:
        rows = [r.get(column) for r in csv.DictReader(f)]
    return rows[:limit] if limit else rows


def _llm(args):
    from .llm import get_llm
    if getattr(args, 'no_llm', False): return None
    return get_llm(required=False)


def cmd_audit_join(args):
    from .fdj import audit_join
    left = _read_column(args.left, args.left_column, args.left_table, args.limit)
    right = _read_column(args.right, args.right_column, args.right_table, args.limit)
    rep = audit_join(left, right, left_name=f'{args.left_table or args.left}.{args.left_column}',
                     right_name=f'{args.right_table or args.right}.{args.right_column}')
    print(json.dumps(rep, indent=2))
    return 0 if not rep['warnings'] else 2


def cmd_extract(args):
    from .extract import ExtractSpec, extract_values
    texts = _read_column(args.source, args.column, args.table, args.limit)
    spec = ExtractSpec(args.name, patterns=args.pattern or (), parse=args.parse, min_coverage=args.min_coverage, unit=args.unit or '')
    res = extract_values(texts, spec, _llm(args), use_llm=not args.no_llm, max_llm_rows=args.max_llm_rows)
    out = {'summary': res.summary(), 'coverage': res.coverage}
    if args.output:
        with open(args.output, 'w', newline='') as f:
            w = csv.writer(f); w.writerow(['text', 'value', 'raw', 'source'])
            for t, r in zip(texts, res.rows): w.writerow([t, r['value'], r['raw'], r['source']])
        out['written'] = args.output
    print(json.dumps(out, indent=2, default=str))
    return 0 if not res.warnings else 2


def cmd_verify_sql(args):
    from .sqlverify import schema_from_sqlite, schema_from_duckdb, schema_from_ddl, verify_sql
    if args.schema.startswith('sqlite:'): schema = schema_from_sqlite(args.schema[7:])
    elif args.schema.startswith('duckdb:'): schema = schema_from_duckdb(args.schema[7:])
    else: schema = schema_from_ddl(Path(args.schema).read_text(), args.dialect)
    if args.dialect: schema.dialect = args.dialect
    sql = Path(args.sql).read_text() if Path(args.sql).exists() else args.sql
    llm = _llm(args)
    if llm is None:
        print('verify-sql needs an LLM (set ANTHROPIC_API_KEY or ~/.config/dab/anthropic_key)', file=sys.stderr); return 3
    res = verify_sql(llm, args.question, sql, schema, methods=tuple(args.methods.split(',')), combine=args.combine, tau=args.tau, n_cases=args.cases)
    print(json.dumps(res, indent=2, default=str))
    print('USAGE', json.dumps(llm.usage.as_dict()), file=sys.stderr)
    return 0 if res['accept'] else 2


def cmd_fdj(args):
    from .fdj import fdj_join
    import pandas as pd
    L = pd.read_csv(args.left).to_dict('records'); R = pd.read_csv(args.right).to_dict('records')
    llm = _llm(args)
    if llm is None: print('fdj needs an LLM', file=sys.stderr); return 3
    res = fdj_join(L, R, args.predicate, llm, T=args.recall, delta=args.delta, k=args.k, k2=args.k, min_pos=args.min_pos)
    print(json.dumps(res.summary(), indent=2))
    if args.output:
        with open(args.output, 'w', newline='') as f:
            w = csv.writer(f); w.writerow(['left_index', 'right_index']); w.writerows(res.matches)
    print('USAGE', json.dumps(llm.usage.as_dict()), file=sys.stderr)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog='dabcheck', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('audit-join'); a.add_argument('left'); a.add_argument('left_column'); a.add_argument('right'); a.add_argument('right_column')
    a.add_argument('--left-table'); a.add_argument('--right-table'); a.add_argument('--limit', type=int); a.set_defaults(fn=cmd_audit_join)
    e = sub.add_parser('extract'); e.add_argument('source'); e.add_argument('column'); e.add_argument('--table'); e.add_argument('--name', required=True)
    e.add_argument('--pattern', action='append', help='regex with a named group (?P<value>...)'); e.add_argument('--parse', default='number', choices=['number', 'amount', 'int', 'text'])
    e.add_argument('--unit'); e.add_argument('--min-coverage', type=float, default=0.95); e.add_argument('--limit', type=int); e.add_argument('--no-llm', action='store_true')
    e.add_argument('--max-llm-rows', type=int); e.add_argument('--output'); e.set_defaults(fn=cmd_extract)
    v = sub.add_parser('verify-sql'); v.add_argument('--question', required=True); v.add_argument('--sql', required=True, help='SQL text or a file')
    v.add_argument('--schema', required=True, help='sqlite:/path, duckdb:/path, or a DDL / pg_dump file'); v.add_argument('--dialect', default=None)
    v.add_argument('--methods', default='rt,se,cohort'); v.add_argument('--combine', default='and', choices=['and', 'or']); v.add_argument('--tau', type=int, default=4)
    v.add_argument('--cases', type=int, default=2); v.set_defaults(fn=cmd_verify_sql)
    f = sub.add_parser('fdj'); f.add_argument('left'); f.add_argument('right'); f.add_argument('--predicate', required=True)
    f.add_argument('--recall', type=float, default=0.9); f.add_argument('--delta', type=float, default=0.1); f.add_argument('--k', type=int, default=400)
    f.add_argument('--min-pos', type=int, default=15); f.add_argument('--output'); f.set_defaults(fn=cmd_fdj)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == '__main__':
    sys.exit(main())
