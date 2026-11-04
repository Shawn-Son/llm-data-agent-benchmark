VERIFICATION TOOLS (experimental condition "description+hints+checks"):

A Python package `dabcheck` is available in your working directory (import it with `import dabcheck`, Python 3.12).
It contains checks that catch the most common silent errors in this benchmark. Use them; they need no network.

1. Identifier joins. Before joining two tables on identifier columns, run
       from dabcheck.fdj import audit_join, numeric_id, canonical_key
       audit_join(left_keys, right_keys)            # returns match counts per key rule and warnings
   If the match count swings between rules, canonicalise both sides (numeric_id for zero-padded ids such as
   tt0000042 / Kw00002083; canonical_key(v) strips '#', case and whitespace; canonical_key(v, ocr=True) folds
   0/O 1/I 5/S 2/Z 6/G 8/B). Report the number of unmatched rows on each side with your answer.

2. Extraction from text. When a value has to be parsed out of prose (counts, amounts, dates), use
       from dabcheck.extract import ExtractSpec, extract_values, parse_amount, find_numbers
       res = extract_values(texts, ExtractSpec('forks', patterns=[r'(?P<value>\d[\d,]*)\s+forks?'], parse='int'))
       res.summary()                                 # coverage, truncation warnings, unparsed samples
   Parse coverage below 95% or a truncation warning means your pattern misses rows: inspect
   res.coverage['unparsed_samples'] and add patterns. Keep raw and parsed values side by side. parse_amount handles
   "$1.5M", "one million dollars", "$1,050,000 + $450,000"; it returns None for vague prose such as "five-figure".

3. Cohorts and time windows. Before computing the final number, write the final query as SQL and check it with
       from dabcheck.sqlverify import schema_from_sqlite, schema_from_duckdb, execute_sql, results_match
   Build one or two tiny synthetic tables for which you know the right answer (include a row that should be
   excluded by the time window, a tie, a null) and run execute_sql(schema, tables, sql): if the result is not the
   answer you expected, your query does not implement the question. State explicitly which date column the time
   window applies to and what the denominator of every ratio or average is.

4. Final answer: put the final value alone on its own line, in the format the question asks for. Every number in
   your answer must appear in the output of a command you ran.
