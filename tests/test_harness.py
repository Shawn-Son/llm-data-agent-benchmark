import json
from dabcheck.harness import sql_from_events, continue_with_warnings, prompt_addendum


def test_sql_recovery_from_codex_and_claude_events(tmp_path):
    ev = [{'type': 'item.completed', 'item': {'type': 'command_execution', 'command':
           "python - <<'PY'\nimport duckdb\ncon.execute(\"SELECT o.OwnerId, AVG(x) FROM Opportunity o JOIN Contract c ON c.Id=o.ContractID__c WHERE o.CreatedDate >= '2023-04-01' GROUP BY 1\")\nPY"}},
          {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Bash', 'input': {'command': "sqlite3 x.db \"select count(*), count(distinct business_ref) from review where date like '2018%'\""}}]}},
          {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Bash', 'input': {'command': 'ls -la'}}]}}]
    p = tmp_path / 'events.jsonl'; p.write_text('\n'.join(json.dumps(e) for e in ev))
    sqls = sql_from_events(p)
    assert sqls == ["SELECT o.OwnerId, AVG(x) FROM Opportunity o JOIN Contract c ON c.Id=o.ContractID__c WHERE o.CreatedDate >= '2023-04-01' GROUP BY 1",
                    "select count(*), count(distinct business_ref) from review where date like '2018%'"]


def test_respond_message_and_addendum():
    assert continue_with_warnings({'checks': [{'sql': 'SELECT 1 FROM t', 'accept': True, 'warnings': []}]}) is None
    msg = continue_with_warnings({'checks': [{'sql': 'SELECT 1 FROM t', 'accept': False, 'warnings': ['date field differs']}]})
    assert 'date field differs' in msg and 'final answer' in msg
    assert 'audit_join' in prompt_addendum() and 'execute_sql' in prompt_addendum()


def test_sql_recovery_multiline_and_quoted_identifiers(tmp_path):
    ev = [{'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Write', 'input': {'content':
           'import duckdb\nq = """\nSELECT o.OwnerId,\n       AVG(x) AS d\nFROM Opportunity o\nWHERE o.CreatedDate >= \'2023-04-01\'\n"""\nprint(con.execute(q).fetchall())\n'}}]}},
          {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Bash', 'input': {'command':
           'python -c "import duckdb; print(duckdb.sql(\'SELECT count(*) FROM \\"Opportunity\\" WHERE x > 1\').fetchall())"'}}]}}]
    p = tmp_path / 'events.jsonl'; p.write_text('\n'.join(json.dumps(e) for e in ev))
    sqls = sql_from_events(p)
    assert sqls[0] == "SELECT o.OwnerId, AVG(x) AS d FROM Opportunity o WHERE o.CreatedDate >= '2023-04-01'"
    assert any(s.startswith('SELECT count(*) FROM "Opportunity" WHERE x > 1') for s in sqls)
