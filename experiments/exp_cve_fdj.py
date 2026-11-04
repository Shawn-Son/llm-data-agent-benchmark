"""cve q3 / q8 / q10 (Identifier joins): KEV cve_ref vs vulns.cves.cve_id over 32 noisy key families.

Offline oracle: DAB ships the deterministic corruption code (query_cve/manual_querycode/corrupt.py),
and every KEV row's `notes` field carries the canonical CVE id. So for each KEV row we can recompute
its noisy key (validates the oracle) and the noisy key the same CVE has in vulns_db, which gives
exact pair labels without any LLM. That oracle plays the role of the join LLM L_p in Alg. 5.

What is measured:
  1. q3 exact answer from the oracle (KEV entries with no vulns record): must equal 1262.
  2. The cheap featurization alone (plain CVE pattern): the share of KEV keys it can link.
  3. FDJ with hand-written code featurizations standing in for the LLM-generated ones (the
     generation loop needs an API key; see docs/dabcheck.md), the oracle as labeller, T = 0.9,
     delta = 0.1: recall against the oracle truth, precision (1 by refinement), the CNF chosen,
     and how many oracle calls the refinement needed versus the cross product.
"""
import importlib.util, random, re, sqlite3, sys
from common import dataset, save, DAB, Timer
from dabcheck.util.pgdump import load_pgdump
from dabcheck.fdj import Featurization, fdj_join, audit_join, cve_candidates
from dabcheck.fdj.featurize import FunctionExtractor
from dabcheck.fdj.canonical import OCR_MAP

_CVE_NOTE = re.compile(r'CVE-(\d{4})-(\d{4,7})', re.I)


def load_corrupt():
    spec = importlib.util.spec_from_file_location('dab_cve_corrupt', DAB / 'query_cve' / 'manual_querycode' / 'corrupt.py')
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


# ---- code featurizations: what an FDJ generation loop would propose for these keys ------------
B36 = '0123456789abcdefghijklmnopqrstuvwxyz'


def _b36(s):
    n = 0
    for ch in s.lower():
        if ch not in B36: return None
        n = n * 36 + B36.index(ch)
    return n


_MARK = re.compile(r'[@#$%~&!?]')


def noise_removals(key: str):
    """The corruption inserts one noise token (letters/digits around a mark character) at a random
    position inside the key. Yield the key with each plausible token removed (and the key itself);
    the decoders run on every variant and the union of decodings is the feature value."""
    yield key
    for m in _MARK.finditer(key):
        for left in range(0, 6):
            for right in range(0, 7):
                a, b = m.start() - left, m.end() + right
                if a < 0 or b > len(key): continue
                if not re.fullmatch(r'[A-Za-z0-9]*[@#$%~&!?][A-Za-z0-9]*', key[a:b]): continue
                yield key[:a] + key[b:]


def decode_families(key: str) -> list:
    """Candidate canonical ids 'YYYY-N' from several key families after noise removal (what an
    LLM-written decoder looks like after a few generation rounds)."""
    out = set()
    for variant in noise_removals(key): out.update(_decode_one(variant))
    return sorted(out)


def _decode_one(key: str) -> set:
    out = set(cve_candidates(key))
    s = key.translate(OCR_MAP)
    for m in re.finditer(r'yr(\d+)_n(\d+)', s): out.add(f'{int(m.group(1)) + 1999}-{int(m.group(2)) - 17}')
    for m in re.finditer(r'n(\d+)_y(\d+)', s): out.add(f'{int(m.group(2)) + 1900}-{int(m.group(1)) - 100000}')
    for m in re.finditer(r'rv(\d{4})-(\d+)', s): out.add(f'{m.group(1)[::-1]}-{int(m.group(2)[::-1])}')
    for m in re.finditer(r'b36y([0-9a-z]+)n([0-9a-z]+)', s.lower()):
        y, n = _b36(m.group(1)), _b36(m.group(2))
        if y and n is not None: out.add(f'{y}-{n}')
    for m in re.finditer(r'h([0-9a-f]+)x([0-9a-f]+)', s.lower()): out.add(f'{int(m.group(1), 16)}-{int(m.group(2), 16)}')
    for m in re.finditer(r'ord(\d\d)\.(\d{7})', s): out.add(f'{2000 + int(m.group(1))}-{int(m.group(2))}')
    for m in re.finditer(r'k(\d{4})(\d{7})', s): out.add(f'{m.group(1)}-{int(m.group(2))}')
    for m in re.finditer(r'off(\d{4})\.(\d+)', s): out.add(f'{int(m.group(1)) - 37}-{int(m.group(2)) - 7919}')
    for m in re.finditer(r'hexmix([0-9a-f]+)_(\d+)', s.lower()): out.add(f'{int(m.group(2)) + 1970}-{int(m.group(1), 16)}')
    for m in re.finditer(r'tri(\d+)-(\d+)', s):
        y, n = int(m.group(1)), int(m.group(2))
        if (y - 2) % 3 == 0 and (n - 4) % 5 == 0: out.add(f'{(y - 2) // 3}-{(n - 4) // 5}')
    for m in re.finditer(r'win([+-]\d+)/(\d+)', s):
        n = int(m.group(2))
        if (n - 1) % 3 == 0: out.add(f'{2010 + int(m.group(1))}-{(n - 1) // 3}')
    for m in re.finditer(r'swap(\d{3})-(\d{4})-(\d{4})', s): out.add(f'{m.group(2)}-{int(m.group(1) + m.group(3))}')
    for m in re.finditer(r'i(\d{11})', s):   # interleave(year, num_pad): y n y n y n y n n n n
        t = m.group(1); out.add(f'{t[0] + t[2] + t[4] + t[6]}-{int(t[1] + t[3] + t[5] + t[7] + t[8:])}')
    for m in re.finditer(r'ri(\d{11})', s):
        t = m.group(1); y = (t[0] + t[2] + t[4] + t[6])[::-1]; n = (t[1] + t[3] + t[5] + t[7] + t[8:])[::-1]; out.add(f'{y}-{int(n)}')
    for m in re.finditer(r'z([0-9a-z]+)\.(\d{4})', s.lower()):
        v = _b36(m.group(1)); y = int(m.group(2)[::-1])
        if v is not None and v > y: out.add(f'{y}-{v - y}')
    return sorted(out)


def digit_stream(key: str) -> str:
    return re.sub(r'\D', '', key.translate(OCR_MAP))


def year_token(key: str):
    m = re.search(r'(?<!\d)(19|20)(\d\d)(?!\d)', key.translate(OCR_MAP))
    return int(m.group(1) + m.group(2)) if m else None


def main():
    t = Timer(); rng = random.Random(0)
    corrupt = load_corrupt()
    kev = load_pgdump(str(dataset('cve') / 'kev.sql')).execute('SELECT cve_ref, notes FROM kev_entries').fetchall()
    vul = sqlite3.connect(f"file:{dataset('cve') / 'vulns.db'}?mode=ro", uri=True)
    vulns_keys = [r[0] for r in vul.execute('SELECT cve_id FROM cves')]
    vulns_set = set(vulns_keys)
    # 1. oracle: canonical id from notes, recomputed noisy keys
    canon, oracle_ok, partner = [], 0, {}
    for ref, notes in kev:
        m = _CVE_NOTE.findall(notes or '')
        cid = f'CVE-{m[-1][0]}-{m[-1][1]}' if m else None
        canon.append(cid)
        if cid and corrupt.reformat_cve_id(cid, 'kev-' + cid) == ref: oracle_ok += 1
        if cid:
            vk = corrupt.reformat_cve_id(cid, 'vulns-' + cid)
            if vk in vulns_set: partner[ref] = vk
    q3_answer = sum(1 for ref in (r for r, _ in kev) if ref not in partner)
    # 2. the cheap featurization alone
    cand_vulns = {}
    for vk in vulns_keys:
        for c in cve_candidates(vk): cand_vulns.setdefault(c, set()).add(vk)
    plain_links = sum(1 for ref, _ in kev if any(c in cand_vulns for c in cve_candidates(ref)))
    plain_correct = sum(1 for ref, _ in kev if ref in partner and any(partner[ref] in cand_vulns.get(c, ()) for c in cve_candidates(ref)))
    # 3. FDJ with the oracle as L_p on L = all KEV refs, R = partners + random vulns keys
    L = [ref for ref, _ in kev]
    partners = sorted(set(partner.values()))
    others = [k for k in vulns_keys if k not in set(partners)]
    R = partners + rng.sample(others, 2000 - len(partners))
    rng.shuffle(R)
    Rpos = {k: j for j, k in enumerate(R)}
    truth = {(i, Rpos[partner[l]]) for i, l in enumerate(L) if l in partner}
    calls = {'n': 0}

    def oracle(l, r):
        calls['n'] += 1
        return int(partner.get(l) == r)
    feats = [Featurization('cve_plain', FunctionExtractor(cve_candidates), FunctionExtractor(cve_candidates), 'set_overlap', 'plain CVE-YYYY-NNNN pattern'),
             Featurization('family_decoders', FunctionExtractor(decode_families), FunctionExtractor(decode_families), 'set_overlap', 'decoders for several key families'),
             Featurization('digit_stream_edit', FunctionExtractor(digit_stream), FunctionExtractor(digit_stream), 'digit_edit', 'edit distance of digit streams (the agents\' loose rule)'),
             Featurization('year_token', FunctionExtractor(year_token), FunctionExtractor(year_token), 'numeric_abs', 'first 4-digit year token')]
    Ridx = {k: j for j, k in enumerate(R)}
    dec_index = {}
    for j, k in enumerate(R):
        for c in decode_families(k): dec_index.setdefault(c, []).append(j)

    # The paper samples S uniformly from L x R with k large enough to hold enough positives; at this
    # density (321 in 3.2M) that would need ~400k oracle labels, so the positives are supplied from the
    # truth set instead (a uniform sample of the positives), which keeps the recall estimate unbiased.
    res = fdj_join(L, R, 'same CVE', labeler=oracle, featurizations=feats, generate=False, T=0.9, delta=0.1, k=600, k2=600,
                   min_pos=60, candidates_fn=lambda: sorted(truth), seed=0)
    found = set(res.matches)
    recall = len(found & truth) / len(truth); precision = len(found & truth) / max(1, len(found))
    out = {'kev_rows': len(kev), 'vulns_rows': len(vulns_keys), 'oracle_recomputed_kev_keys': oracle_ok, 'kev_with_vulns_partner': len(partner),
           'q3_oracle_answer': q3_answer, 'q3_ground_truth': 1262,
           'plain_pattern': {'kev_keys_linked_to_any_vulns_key': plain_links, 'correct_links': plain_correct},
           'fdj': {'L': len(L), 'R': len(R), 'true_pairs': len(truth), 'matches': len(found), 'recall': recall, 'precision': precision,
                   'decomposition': res.scaffold.describe(feats), 'adjusted_target': res.adjusted_target, 'sample_recall': res.sample_recall,
                   'labelled_pairs': res.n_labeled, 'refinement_calls': res.n_refined, 'target_feasible': res.target_feasible, 'oracle_calls_total': calls['n'],
                   'cross_product': len(L) * len(R), 'construction_log': res.log},
           'audit': audit_join(L, R, rules={'raw': lambda v: v, 'plain_cve': lambda v: ','.join(cve_candidates(v)) or None,
                                             'family_decoders': lambda v: ','.join(decode_families(v)) or None}, left_name='kev.cve_ref', right_name='vulns.cve_id'),
           'seconds': t()}
    md = ['# cve identifier join with FDJ (offline, oracle labels)', '',
          f"KEV rows {len(kev)}; vulns rows {len(vulns_keys)}; oracle recomputes {oracle_ok}/{len(kev)} KEV keys exactly; "
          f"{len(partner)} KEV entries have a vulns record; q3 answer from the oracle = {q3_answer} (ground truth 1262).", '',
          f"Plain CVE pattern alone links {plain_links} KEV keys to some vulns key ({plain_correct} correctly).", '',
          f"FDJ (T=0.9, delta=0.1) on L={len(L)} x R={len(R)} ({len(L) * len(R)} pairs, {len(truth)} true):", 
          f"- decomposition: {res.scaffold.describe(feats)}", f"- adjusted recall target T' = {res.adjusted_target:.3f}, sample recall {res.sample_recall:.3f}",
          f"- recall {recall:.3f}, precision {precision:.3f}, matches {len(found)}; recall target feasible on the sample: {res.target_feasible}",
          f"- oracle (L_p) calls: {res.n_labeled} labels + {res.n_refined} refinement = {calls['n']} vs {len(L) * len(R)} for the naive all-pairs join",
          '', 'Join audit (match counts by rule): ' + ', '.join(f"{k}={v['matched_keys']}" for k, v in out['audit']['rules'].items())]
    save('cve_fdj', out, '\n'.join(md) + '\n'); print('\n'.join(md)); print('seconds', t())


if __name__ == '__main__': main()
