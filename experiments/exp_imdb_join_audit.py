"""imdb q6 / q10 (Identifier joins): keyword.id vs movie_keyword.keyword_id.

The failure review found that comparing digit strings without dropping leading zeros kept only
119 of 937 candidate movies (H1) while casting to integers found all of them (H2). audit_join
reports the match count under each key rule and fires the leading-zero warning, without an LLM.
Also reproduces the q10 keyword filter under both rules on the real data.
"""
from common import dataset, save, Timer
from dabcheck.util.pgdump import load_pgdump
from dabcheck.fdj import audit_join, numeric_id

KEYWORDS = ['superhero', 'marvel-comics', 'based-on-comic', 'tv-special', 'fight', 'violence', 'magnet', 'web', 'claw', 'laser']


def main():
    t = Timer()
    import os, tempfile
    tmp = os.path.join(tempfile.gettempdir(), 'dabcheck_imdb_keywords.sqlite')   # 4.5M movie_keyword rows: keep them on disk
    if not os.path.exists(tmp): load_pgdump(str(dataset('imdb') / 'movies.sql'), ['keyword', 'movie_keyword'], sqlite_path=tmp).close()
    import sqlite3
    con = sqlite3.connect(tmp)
    kw = con.execute('SELECT id, keyword FROM keyword').fetchall()
    mk_counts = dict(con.execute('SELECT keyword_id, COUNT(*) FROM movie_keyword GROUP BY keyword_id').fetchall())
    n_mk = sum(mk_counts.values())
    print(f'loaded keyword={len(kw)} movie_keyword={n_mk} ({len(mk_counts)} distinct keyword_id) in {t()}s')
    report = audit_join([k for k, _ in kw], mk_counts, left_name='keyword.id', right_name='movie_keyword.keyword_id')
    # q10 keyword filter: movies tagged with any of the keywords, under the two rules the agents used
    wanted = {k for k, w in kw if w in KEYWORDS}
    digits = lambda s: ''.join(ch for ch in str(s) if ch.isdigit())
    wanted_digits = {digits(x) for x in wanted}; wanted_int = {numeric_id(x) for x in wanted}
    movies_digit_string, movies_numeric = set(), set()
    for k, m in con.execute('SELECT keyword_id, movie_id FROM movie_keyword'):
        if digits(k) in wanted_digits: movies_digit_string.add(m)
        if numeric_id(k) in wanted_int: movies_numeric.add(m)
    out = {'audit': report, 'q10_keyword_filter': {'keywords': KEYWORDS, 'keyword_rows': len(wanted),
           'movies_digit_string_rule': len(movies_digit_string), 'movies_numeric_id_rule': len(movies_numeric)}, 'seconds': t()}
    md = ['# imdb identifier join audit (offline)', '', f'keyword rows: {len(kw)}, movie_keyword rows: {n_mk}', '',
          '| rule | matched keys | left unmatched rows | right unmatched rows |', '|---|---:|---:|---:|']
    for r, s in report['rules'].items():
        md.append(f"| {r} | {s['matched_keys']} | {s['left_unmatched_rows']} | {s['right_unmatched_rows']} |")
    md += ['', 'Warnings:'] + [f'- {w}' for w in report['warnings']]
    md += ['', f'q10 keyword filter: digit-string rule links {len(movies_digit_string)} movies, numeric-id rule links {len(movies_numeric)} movies.']
    save('imdb_join_audit', out, '\n'.join(md) + '\n')
    print('\n'.join(md))


if __name__ == '__main__': main()
