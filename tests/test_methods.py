"""Method conditions (fdj / docetl / sqlverify): harness configuration, dataset access, preprocessing,
staging, verification routing and the second round. No API key, no network, no DAB data."""
import csv, json, sqlite3, stat
from pathlib import Path

import pytest
import yaml

import native104
from dabcheck.dabdata import DABDataset
from dabcheck.llm import LLM, MockLLM, BudgetExceeded
from dabcheck import methods, prep


# ---------------------------------------------------------------- fixture dataset

def make_dataset(root: Path, name='toy'):
    d = root / f'query_{name}'; qd = d / 'query_dataset'; qd.mkdir(parents=True)
    con = sqlite3.connect(qd / 'a.db')
    con.execute('CREATE TABLE items (item_id TEXT, note TEXT)')
    con.executemany('INSERT INTO items VALUES (?, ?)', [('IT-001', 'has 1,234 stars and 56 forks'), ('IT-002', 'starred 7 times'),
                                                        ('IT-003', 'no numbers here'), ('IT-001', 'duplicate id')])
    con.commit(); con.close()
    import duckdb
    dc = duckdb.connect(str(qd / 'b.duckdb'))
    dc.execute('CREATE TABLE orders (order_id VARCHAR, item_ref VARCHAR, created DATE, amount_text VARCHAR)')
    dc.execute("INSERT INTO orders VALUES ('o1', 'it_001', DATE '2023-04-02', '$1,500'), ('o2', 'IT 002', DATE '2023-05-01', 'one million dollars')")
    dc.close()
    (qd / 'c.sql').write_text('CREATE TABLE public.refs (\n    ref_id text,\n    label text\n);\n\n'
                              'COPY public.refs (ref_id, label) FROM stdin;\nR1\talpha\nR2\t\\N\n\\.\n')
    import bson
    (qd / 'dump' / 'docsdb').mkdir(parents=True)
    with open(qd / 'dump' / 'docsdb' / 'docs.bson', 'wb') as f:
        for doc in ({'key': 'IT-001', 'meta': {'lang': 'en'}}, {'key': 'it-002'}, {'key': 'IT-001'}):
            f.write(bson.encode(doc))
    cfg = {'db_clients': {'a_db': {'db_type': 'sqlite', 'db_path': 'query_dataset/a.db'},
                          'b_db': {'db_type': 'duckdb', 'db_path': 'query_dataset/b.duckdb'},
                          'c_db': {'db_type': 'postgres', 'db_name': 'c', 'sql_file': 'query_dataset/c.sql'},
                          'd_db': {'db_type': 'mongo', 'db_name': 'docsdb', 'dump_folder': 'query_dataset/dump'}}}
    (d / 'db_config.yaml').write_text(yaml.safe_dump(cfg))
    return DABDataset(root, name)


def test_dataset_access_all_four_kinds(tmp_path):
    ds = make_dataset(tmp_path)
    assert sorted(ds.column('a_db', 'items', 'item_id')) == ['IT-001', 'IT-002', 'IT-003']
    assert ds.column('b_db', 'orders', 'item_ref') == ['it_001', 'IT 002'] or sorted(ds.column('b_db', 'orders', 'item_ref')) == ['IT 002', 'it_001']
    assert ds.column('c_db', 'refs', 'label') == ['alpha']
    assert ds.column('d_db', 'docs', 'key') == ['IT-001', 'it-002']
    assert ds.rows('d_db', 'docs', ['key', 'meta.lang'])[0] == {'key': 'IT-001', 'meta.lang': 'en'}
    sc = ds.sql_schemas()
    assert set(sc) == {'a_db', 'b_db', 'c_db'}
    assert 'refs' in sc['c_db'].tables and sc['c_db'].dialect == 'postgres' and sc['b_db'].dialect == 'duckdb'


# ---------------------------------------------------------------- LLM guards

def test_llm_model_guard_and_budget(tmp_path):
    llm = LLM(model='claude-haiku-5-5', cheap_model='claude-haiku-5-5', api_key='test', cache=False,
              allowed_models={'claude-haiku-5-5'}, budget_usd=0.01)
    with pytest.raises(ValueError):
        llm.complete('hi', model='claude-sonnet-5-5')
    llm.usage.cost_usd = 0.02
    with pytest.raises(BudgetExceeded):
        llm.complete('hi')
    with pytest.raises(ValueError):
        LLM(model='claude-sonnet-5-5', cheap_model='claude-haiku-5-5', api_key='test', allowed_models={'claude-haiku-5-5'})


# ---------------------------------------------------------------- harness configuration

def test_configure_method_paths_and_protection():
    out = native104.configure('claude', None, 1, None, False, 'fdj')
    assert out == native104.METHOD_ARTIFACTS / 'haiku-claude-fdj-104x3' / 'trial1'
    assert native104.condition() == 'description+hints+fdj' and native104.MODEL == 'claude-haiku-5-5'
    prot = [str(p) for p in native104.protected_paths()]
    assert str(out) not in prot
    assert str(native104.METHOD_ARTIFACTS / 'haiku-claude-fdj-104x3' / 'trial2') in prot
    assert str(native104.METHOD_ARTIFACTS / 'haiku-claude-sqlverify-104x3' / 'trial1') in prot
    assert str(native104.ARTIFACTS / 'haiku-claude-104x3' / 'trial1') in prot        # baseline answers stay hidden
    assert str(native104.METHOD_ARCHIVES) in prot and str(native104.PREP_ROOT) not in prot
    with pytest.raises(AssertionError): native104.configure('claude', None, None, None, False, 'fdj')
    with pytest.raises(AssertionError): native104.configure('claude', None, 1, None, True, 'docetl')
    base = native104.configure('claude', None, 2, None, False, None)                  # baseline layout unchanged
    assert base == native104.ARTIFACTS / 'haiku-claude-104x3' / 'trial2' and native104.condition() == 'description+hints'


# ---------------------------------------------------------------- preprocessing + staging

def test_docetl_prep_stage_and_readme(tmp_path, monkeypatch):
    make_dataset(tmp_path / 'dab')
    spec = {'name': 'item_counts', 'dataset': 'toy', 'source': ('a_db', 'items', ['item_id'], 'note'),
            'extract': [{'name': 'stars', 'parse': 'int', 'patterns': [prep.SPECS['docetl'][0]['extract'][1]['patterns'][0]]}]}
    monkeypatch.setitem(prep.SPECS, 'docetl', [spec])

    def handler(user, system, tag):
        if 'starred 7 times' in user: return json.dumps({'value': 7, 'evidence': 'starred 7 times'})
        if 'should_refine' in user or 'refine' in tag: return json.dumps({'should_refine': False, 'improvements': ''})
        return json.dumps({'value': None, 'evidence': ''})
    monkeypatch.setattr('dabcheck.llm.LLM', lambda **kw: MockLLM(handler))
    out = tmp_path / 'prep'
    prep.main(['--method', 'docetl', '--dab-root', str(tmp_path / 'dab'), '--out', str(out), '--dry-run'])
    assert not (out / 'docetl' / 'toy' / 'MANIFEST.json').exists()
    prep.main(['--method', 'docetl', '--dab-root', str(tmp_path / 'dab'), '--out', str(out)])
    d = out / 'docetl' / 'toy'
    man = json.loads((d / 'MANIFEST.json').read_text())
    assert man['specs']['item_counts']['csv'] == 'docetl_item_counts.csv'
    rows = list(csv.DictReader((d / 'docetl_item_counts.csv').open()))
    assert [r['stars'] for r in rows] == ['1234', '7', '', '']
    assert [r['stars_source'] for r in rows] == ['code', 'llm', '', '']
    assert 'docetl_item_counts.csv' in (d / 'README.md').read_text()
    work = tmp_path / 'work'; work.mkdir()
    staged = methods.stage_prep(out, 'docetl', 'toy', work)
    assert sorted(p.name for p in staged.iterdir()) == ['README.md', 'docetl_item_counts.csv']
    assert not (staged / 'README.md').stat().st_mode & stat.S_IWUSR       # read-only for the agent
    assert methods.stage_prep(out, 'docetl', 'other', work) is None
    assert 'dabcheck_prep' in methods.prompt_addendum('docetl')


def test_fdj_prep_dry_run_and_failure_is_recorded(tmp_path, monkeypatch):
    make_dataset(tmp_path / 'dab')
    spec = {'name': 'refs', 'dataset': 'toy', 'left': ('b_db', 'orders', 'item_ref'), 'right': ('a_db', 'items', 'item_id'), 'predicate': 'same item'}
    monkeypatch.setitem(prep.SPECS, 'fdj', [spec])
    out = tmp_path / 'prep'
    prep.main(['--method', 'fdj', '--dab-root', str(tmp_path / 'dab'), '--out', str(out), '--dry-run'])
    dry = json.loads((out / 'fdj' / 'dry_run.json').read_text())['specs']['toy/refs']
    assert dry['left_size'] == 2 and dry['right_size'] == 3 and dry['cross_product'] == 6

    def broken(user, system, tag): raise RuntimeError('api down')
    monkeypatch.setattr('dabcheck.llm.LLM', lambda **kw: MockLLM(broken))
    prep.main(['--method', 'fdj', '--dab-root', str(tmp_path / 'dab'), '--out', str(out)])
    man = json.loads((out / 'fdj' / 'toy' / 'MANIFEST.json').read_text())
    assert man['specs']['refs']['status'] == 'failed' and not man['specs']['refs'].get('csv')
    assert not methods.has_prep(out, 'fdj', 'toy')


def test_fdj_pair_space_limits_evaluation():
    from dabcheck.fdj import Featurization, fdj_join
    from dabcheck.fdj.featurize import FunctionExtractor
    L = [f'k{i}' for i in range(30)]; R = [f'K{i}' for i in range(30)]
    feat = Featurization('lower', FunctionExtractor(lambda v: v.lower(), 'l'), FunctionExtractor(lambda v: v.lower(), 'r'), 'char_edit', 'lowercase')
    oracle = lambda l, r: int(l.lower() == r.lower())
    space_calls = []
    def space():
        space_calls.append(1); return [(i, i) for i in range(30)]
    res = fdj_join(L, R, 'same', labeler=oracle, featurizations=[feat], generate=False, min_train_pos=5, n_train_neg=20,
                   discovery_pos=3, discovery_neg=10, pair_space=space, candidates_fn=lambda: [(i, i) for i in range(30)], max_uniform=50)
    assert sorted(res.matches) == [(i, i) for i in range(30)]
    assert space_calls   # char_edit is not an exact block, so the supplied space was used


# ---------------------------------------------------------------- sqlverify routing and the second round

def test_pick_database_and_round2_prompt(tmp_path):
    ds = make_dataset(tmp_path)
    sc = ds.sql_schemas()
    assert methods.pick_database("SELECT count(*) FROM orders WHERE created >= '2023-04-01'", sc) == 'b_db'
    assert methods.pick_database('WITH x AS (SELECT * FROM refs) SELECT * FROM x', sc) == 'c_db'
    assert methods.pick_database('SELECT * FROM orders JOIN items ON 1=1', sc) is None   # spans two databases
    assert methods.round2_prompt('Q', 'A', {'checks': [{'sql': 'SELECT 1 FROM t', 'accept': True, 'warnings': []}]}) is None
    msg = methods.round2_prompt('QUESTION', '42', {'checks': [{'sql': 'SELECT 1 FROM t', 'accept': False, 'warnings': ['date field differs']}]})
    assert msg.startswith('QUESTION') and '42' in msg and 'date field differs' in msg and 'verifier can be wrong' in msg


def test_sqlverify_round_grades_round_two(tmp_path, monkeypatch):
    native104.configure('claude', None, 1, None, False, 'sqlverify')
    folder = tmp_path / 'q'; work = folder / 'work'; work.mkdir(parents=True)
    (folder / 'events.jsonl').write_text('')
    answer = work / 'answer.txt'; answer.write_text('wrong')
    monkeypatch.setattr(native104, 'verifier', lambda ds: (MockLLM(), {}))
    monkeypatch.setattr('dabcheck.methods.verify_run', lambda *a, **k: {'sql_found': 1, 'queries_checked': 1, 'any_rejected': True,
                        'checks': [{'sql': 'SELECT 1 FROM t', 'accept': False, 'warnings': ['window']}]})
    monkeypatch.setattr(native104, 'question_text', lambda ds, q: 'Q?')

    def fake_session(folder, work, home, env, cmd, source, events, stderr, ans, key):
        assert 'window' in source and events == 'events_round2.jsonl'
        (folder / events).write_text(''); ans.write_text('right'); return 'completed', 0, None
    monkeypatch.setattr(native104, 'run_session', fake_session)
    monkeypatch.setattr(native104, 'official_grade', lambda root, ds, q, a: {'status': 'scored', 'passed': Path(a).read_text() == 'right'})
    monkeypatch.setattr(native104, 'stats', lambda p: ({'input_tokens': 10, 'tool_calls': 2, 'estimated_cost_usd': 0.01}, [{'c': 2}]))
    record = {}
    st, cmds, grading = native104.sqlverify_round(folder, work, folder, {}, [], 'ORIGINAL', answer, 'KEY', 'toy', 1, record,
                                                  {'input_tokens': 5, 'tool_calls': 1, 'estimated_cost_usd': 0.02}, [{'c': 1}],
                                                  {'status': 'scored', 'passed': False})
    assert grading['passed'] is True and record['round1_passed'] is False and record['round2_passed'] is True
    assert (folder / 'answer_round1.txt').read_text() == 'wrong' and json.loads((folder / 'grading_round1.json').read_text())['passed'] is False
    assert st['input_tokens'] == 15 and st['tool_calls'] == 3 and abs(st['estimated_cost_usd'] - 0.03) < 1e-9 and len(cmds) == 2
    native104.configure('claude', None, 2, None, False, None)
