#!/usr/bin/env python3
"""Render the retrospective review without rerunning inference or altering grades.

Usage: python3 build_review45.py [directory containing review45.json]
The dataset counts are the verified fixed 104-question run, not new measurements.
"""
import collections
import csv
import html
import json
import pathlib
import sys

DATASETS = [('DEPS_DEV_V1',1,2),('GITHUB_REPOS',3,4),('PANCANCER_ATLAS',1,3),('PATENTS',2,3),('agnews',1,4),('bookreview',3,3),('civic_unstructured',3,10),('crmarenapro',10,13),('cve',2,10),('googlelocal',4,4),('imdb',7,10),('krama',4,10),('music_brainz_20k',3,3),('stockindex',3,3),('stockmarket',4,5),('usaspending',4,10),('yelp',4,7)]
ROOT = 'https://github.com/Shawn-Son/llm-data-agent-benchmark/blob/main/results/terra-native-104x1/'
EXAMPLES = [
 ('Extraction and representation','DEPS q1: star regex misses label-first/comma-formatted counts; imdb q6 copies shortened IDs.','Low parse coverage; IDs change after copying output.','Keep raw + parsed values; use machine-readable joins.','Potentially; not tested.'),
 ('Identifier joins and identity','CVE q6: similarity thresholds change candidate matches sharply; krama q7 aligns patients by position.','Unmatched/duplicate keys or unstable match counts.','Canonical keys, cardinality checks, patient-ID joins.','Partly; identity may need adjudication.'),
 ('Cohort and aggregation','PANCANCER q3: N=1059 gives 305.12, then N=762 gives final 325.34. Yelp q2 mixes metadata counts with review rows.','Population changes; ranking and average use different sources.','Record cohort lineage and each aggregate denominator.','Potentially; semantics still matter.'),
 ('Temporal state and status','Civic q6 applies a static disaster blacklist despite an as-of-grant requirement; 123.003M versus 88.615M.','Time-dependent eligibility has no dated join.','Use latest report at or before each grant.','Partly; report interpretation needed.'),
 ('Semantic classification','agnews q2 labels 18/111 as Science/Technology; validator implies 16/111.','Labels change across rules or disagree on an audited sample.','Review disputed labels and policy clauses.','Uncertain; exact disputed rows unresolved.'),
 ('Execution and unsupported result','krama q2: geometry parser fails; final Wyoming lacks a successful intersection (expected Idaho).','Calculation fails but a confident result follows.','Require a successful geometry computation.','Potentially; repair not tested.'),
 ('Final-answer rounding','krama q9: tool 2.4431451613 should round to 2.4431; final says 2.4432.','Final number differs from the cited tool value at requested precision.','Format directly from the computed scalar.','Deterministic example; no agent replay.')
]

def table(headers, rows):
    esc = lambda v: str(v).replace('|','\\|').replace('\n',' ')
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+['| '+' | '.join(map(esc,r))+' |' for r in rows])

def main(folder):
    folder = pathlib.Path(folder)
    obj=json.loads((folder/'review45.json').read_text())
    reviews=obj['reviews']
    assert len(reviews)==45 and len({(r['dataset'],r['query']) for r in reviews})==45
    assert all(r['official_grading']['passed'] is False and r['command_ids'] for r in reviews)
    counts=collections.Counter(r['category'] for r in reviews)
    statuses=collections.Counter(r['evidence_status'] for r in reviews)
    assert sum(x[1] for x in DATASETS)==59 and sum(x[2] for x in DATASETS)==104
    expected_failures={d:n-k for d,k,n in DATASETS if n>k}
    assert dict(collections.Counter(r['dataset'] for r in reviews))==expected_failures
    macro=sum(k/n for _,k,n in DATASETS)/17*100
    summary='# DataAgentBench: gpt-5.6-terra results and all-failure review\n\n'
    summary+='## 1. Performance and scope\n\n'
    summary+='104 original questions across 17 datasets, one independent trial each, original descriptions + hints, unchanged validators. **59 correct, 45 wrong, 0 unscored. Micro accuracy: 56.73%%; equal-dataset macro Pass@1: %.2f%%. Pass@5 was not measured.**\n\n'%macro
    summary+='The reconstructed Codex CLI harness differs from the authors\' exact driver/system prompt/timeouts, so this is not a controlled ranking against their models. Earlier infrastructure failures were corrected and excluded by the documented rule; the final sweep completed. Internal failed commands can still occur within scored trials.\n\n'
    summary+=table(['Model','Correct / total','Micro accuracy','Macro Pass@1','Tool calls'],[['gpt-5.6-terra','59 / 104','56.73%','%.2f%%'%macro,'1,226']])+'\n\n'
    summary+='Recorded usage: 34,994,764 input tokens (14,814,739 cached) and 558,239 output tokens. Actual dollar billing was not verified.\n\n'
    summary+='## 2. Dataset detail\n\n'+table(['Dataset','Correct / total','Accuracy'],[(d,'%s/%s'%(k,n),'%.1f%%'%(100*k/n)) for d,k,n in DATASETS])+'\n\n'
    summary+='CVE, civic_unstructured, krama and usaspending account for **27/45 failures (60%)**. Four datasets are perfect in this single small run; this does not establish general reliability.\n\n'
    summary+='## 3. What went wrong, and what to catch during execution\n\n'
    summary+='All 45 failed traces were reviewed (35 added to the earlier 10). **16 have a directly visible mechanism or discrepancy; 29 remain unresolved at the exact-cause/row level.** This is a retrospective assistant review, not a second independent judge. Each failure receives one primary review category. Shares below describe review categories, including hypotheses; they are not proven causal rates or repair rates.\n\n'
    summary+=table(['Primary review category','Runs','Share of 45'],[(c,counts[c],'%.1f%%'%(100*counts[c]/45)) for c,*_ in EXAMPLES])+'\n\n'
    summary+=table(['Category / real example','When to warn','What to do','Can we fix it?'],[(c+': '+e,w,a,f) for c,e,w,a,f in EXAMPLES])+'\n\n'
    summary+='The most concrete opportunity is preserving computed results and their population: krama q9 has a rounding error; PANCANCER q3 and krama q3 contain validator-matching intermediate calculations before a different cohort is selected. An intermediate number matching the key alone is not proof of a valid algorithm (notably CVE q9/q10).\n\n'
    summary+='**Possible task/validator ambiguities:** imdb q9 asks for an alphabetically first vote count; the trace returns 101188 while the validator requires 1040. Stockmarket q4 has an unresolved ranking interpretation; crmarenapro q12 differs between created-month and signed-month cohorts. Keep official grades unchanged pending adjudication. The screenshot\'s 352 failures, model scores and LIMIT examples describe another experiment and are not reused here.\n\n'
    summary+='## 4. Improvement: what is measured and what is not\n\n'
    summary+='No runtime-warning or repair intervention was tested. There is no measured repair rate, fixable-failure total or supported upper-bound accuracy estimate. Each additional corrected question would add 1/104 = 0.96 percentage points to micro accuracy. If a future intervention fixes 1, 5 or 10 failures with no regressions, accuracy would be 57.69%, 61.54% or 66.35%, respectively. These are arithmetic scenarios, not forecasts.\n\n'
    summary+='Next experiment: compare an unchanged rerun control against warnings for (1) final-value consistency, (2) cohort/denominator changes and (3) join/parse coverage. Hold model and budget fixed; measure net corrections, regressions, false warnings, extra tokens and latency with unchanged validators. Resolve ambiguous tasks separately, without tuning detectors to known answer values.\n\n'
    summary+='## 5. Evidence and completion record\n\n'
    summary+='Slurm sweep 65052253 and archive job 65056532 completed. Original source commit: `61fb21e0766d775acae443f6074f5d498e95f938`. Full retained trajectories and validators are on Great Lakes. The original 484,033,085-byte archive has SHA-256 `4c2135f695e9ca03bd1d35e109465bbb1ba91ba5fea435aac9834b219abb8b00`; this later review is a separate supplement and does not change that archive or its grades.\n\n'
    summary+='[Per-question results]('+ROOT+'runs.csv) · [Original archive record]('+ROOT+'ARCHIVE.json) · [Structured 45-case review]('+ROOT+'review45.json) · [Review generator]('+ROOT+'build_review45.py)\n\n'
    report=summary+'## Appendix: all 45 failed runs\n\n'+obj['method']+'\n\n'
    for r in reviews:
        report+='### %s q%s — %s\n\n'%(r['dataset'],r['query'],r['category'])
        report+='**Evidence status:** '+r['evidence_status']+'. **Repair tested:** No.\n\n'+r['observation']+'\n\n'
        report+='**Check/action:** '+r['proposed_check']+'\n\n'
        report+='**Official validator:** '+r['official_grading']['reason'].replace('\n',' ')+'\n\n'
        report+='**Trace:** `'+r['source']+'`; '+', '.join('`'+i+'`' for i in r['command_ids'])+'. Validator SHA-256: `'+r['official_grading']['validator_sha256']+'`.\n\n'
    (folder/'review45.md').write_text(report)
    (folder/'tab5-summary.md').write_text(summary)
    with (folder/'review45.csv').open('w',newline='') as f:
        fields=['dataset','query','category','evidence_status','observation','proposed_check','command_ids','source','repair_tested']
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(reviews)
    # Deliberately simple HTML for a readable archival copy, without dependencies.
    def render(md):
        lines=md.splitlines(); out=[]; i=0
        while i<len(lines):
            l=lines[i]
            if l.startswith('| ') and i+1<len(lines) and lines[i+1].startswith('| ---'):
                headers=[x.strip() for x in l.strip('|').split('|')];i+=2
                out.append('<table><tr>'+''.join('<th>'+html.escape(x)+'</th>' for x in headers)+'</tr>')
                while i<len(lines) and lines[i].startswith('| '):
                    out.append('<tr>'+''.join('<td>'+html.escape(x.strip())+'</td>' for x in lines[i].strip('|').split('|'))+'</tr>');i+=1
                out.append('</table>');continue
            if l.startswith('#'):
                level=len(l)-len(l.lstrip('#'));out.append('<h%d>%s</h%d>'%(level,html.escape(l[level:].strip()),level))
            elif l: out.append('<p>'+html.escape(l).replace('**','').replace('`','')+'</p>')
            i+=1
        return '<html><head><meta charset="utf-8"><style>body{font:11pt Arial;max-width:1100px;margin:36px auto;line-height:1.35}table{border-collapse:collapse;width:100%;margin:12px 0}td,th{border:1px solid #888;padding:7px;vertical-align:top}th{background:#eee;text-align:left}h1{font-size:22pt}h2{font-size:16pt}</style></head><body>'+''.join(out)+'</body></html>'
    (folder/'review45.html').write_text(render(report))
    (folder/'tab5-summary.html').write_text(render(summary))
    print(json.dumps({'reviews':len(reviews),'statuses':dict(statuses),'categories':dict(counts),'micro_accuracy':59/104,'macro_pass1':macro/100,'grades_changed':False},indent=2))

if __name__=='__main__':
    main(sys.argv[1] if len(sys.argv)>1 else pathlib.Path(__file__).parent)
