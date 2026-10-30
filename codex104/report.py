from pathlib import Path
from collections import defaultdict
import csv,html,json,statistics

def summarize(rows):
 seen=set();groups=defaultdict(list)
 for r in rows:
  key=(r['dataset'],r['query'],r['trial'])
  if key in seen:raise ValueError('Duplicate task/trial: '+str(key))
  seen.add(key);groups[r['dataset']].append(r)
 ds=[]
 for d,rs in sorted(groups.items()):
  scored=[r for r in rs if r['status']=='completed' and r.get('grading_status')=='scored' and r.get('passed') is not None]
  ds.append({'dataset':d,'attempted':len(rs),'scored':len(scored),'correct':sum(r['passed'] for r in scored),
             'accuracy':sum(r['passed'] for r in scored)/len(scored) if scored else None,
             'unscored':len(rs)-len(scored)})
 scores=[d['accuracy'] for d in ds if d['accuracy'] is not None]
 total={'model':'gpt-5.6-terra','attempted':len(rows),'expected':104,'datasets':len(ds),'expected_datasets':17,
        'complete':len(seen)==104 and len(ds)==17 and all(d['unscored']==0 for d in ds),
        'dataset_macro_pass1':statistics.mean(scores) if scores else None,'pass5':None,
        'scored':sum(d['scored'] for d in ds),'correct':sum(d['correct'] for d in ds),
        'unscored':sum(d['unscored'] for d in ds),'coverage_note':'Macro score is partial unless complete is true.',
        'estimated_cost_usd':sum(r['estimated_cost_usd'] for r in rows) if rows and all(r.get('estimated_cost_usd') is not None for r in rows) else None,
        'cost_note':'Pricing was not verified; estimated cost is unavailable. Token usage is retained; consult actual U-M Toolkit billing.'}
 return total,ds

def generate(out):
 out=Path(out);rows=[json.loads(p.read_text()) for p in sorted(out.glob('runs/*/query*/result.json'))]
 if not rows:raise ValueError('No actual result files; no accuracy report fabricated')
 total,ds=summarize(rows)
 total['question_micro_accuracy']=total['correct']/total['scored'] if total['scored'] else None
 total['input_tokens']=sum(r.get('input_tokens',0) for r in rows)
 total['cached_input_tokens']=sum(r.get('cached_input_tokens',0) for r in rows)
 total['output_tokens']=sum(r.get('output_tokens',0) for r in rows)
 total['tool_calls']=sum(r.get('tool_calls',0) for r in rows)
 dest=out/'reports';dest.mkdir(exist_ok=True)
 def csvwrite(path,rs):
  keys=list(dict.fromkeys(k for r in rs for k in r))
  with (dest/path).open('w',newline='') as f:
   w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rs)
 cols=['model','dataset','query','trial','condition','status','grading_status','passed','duration_s','tool_calls','command_calls','command_errors','api_errors','input_tokens','cached_input_tokens','output_tokens','estimated_cost_usd','answer']
 csvwrite('runs.csv',[{k:r.get(k) for k in cols} for r in rows]);csvwrite('datasets.csv',ds)
 failures=[]
 for r in rows:
  if r.get('passed') is True:continue
  folder=out/'runs'/r['dataset']/f"query{r['query']}"
  grading=json.loads((folder/'grading.json').read_text()) if (folder/'grading.json').exists() else {}
  failures.append({'dataset':r['dataset'],'query':r['query'],'category':'infrastructure' if r['status']!='completed' else 'grader_error' if r.get('grading_status')!='scored' else 'answer_mismatch',
                   'official_reason':grading.get('reason'),'answer':r.get('answer'),'command_errors':r.get('command_errors'),
                   'trace':str((folder/'events.jsonl').relative_to(out)),'semantic_root_cause':'Not yet manually reviewed','review_evidence':''})

 notes_path=dest/'review-notes.json'
 notes=json.loads(notes_path.read_text()).get('reviews',[]) if notes_path.exists() else []
 note_map={(n['dataset'],n['query']):n for n in notes}
 for f in failures:
  n=note_map.get((f['dataset'],f['query']))
  if n:f.update(semantic_root_cause=n['category'],review_evidence=n['evidence'],review_status=n['review_status'])

 if failures:csvwrite('failure_analysis.csv',failures)
 (dest/'summary.json').write_text(json.dumps({'summary':total,'datasets':ds,'failures':failures},indent=2))
 title='Terra DataAgentBench — '+('complete 104-task evaluation' if total['complete'] else 'partial evaluation')
 svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="950" height="{70+32*len(ds)}"><rect width="100%" height="100%" fill="white"/><text x="20" y="28" font-size="18">{html.escape(title)}</text>']
 for i,d in enumerate(ds):
  y=50+32*i;v=d['accuracy'];label='N/A' if v is None else f'{v:.1%}'
  svg.append(f'<text x="20" y="{y+17}">{html.escape(d["dataset"])}</text><rect x="230" y="{y}" width="{(v or 0)*540}" height="23" fill="#2563eb"/><text x="790" y="{y+17}">{label} ({d["scored"]} scored)</text>')
 svg.append('</svg>');chart=''.join(svg);(dest/'accuracy.svg').write_text(chart)
 def table(rs,columns):
  return '<table><thead><tr>'+''.join('<th>'+html.escape(k)+'</th>' for k in columns)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(r.get(k,'')))+'</td>' for k in columns)+'</tr>' for r in rs)+'</tbody></table>'
 intro='One independent trial per original question, descriptions+hints. Original query-specific validators. Pass@5 is not available. Authors native Codex driver was unavailable; this is a documented Codex CLI reconstruction. Offline/connection tests are excluded. Infrastructure failures are separate from wrong answers.'
 (dest/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>'+html.escape(title)+'</title><style>body{font:15px system-ui;margin:32px;color:#162236}table{border-collapse:collapse;margin:24px 0}th,td{border:1px solid #ddd;padding:8px}th{background:#edf2ff}svg{max-width:100%;height:auto}</style><h1>'+html.escape(title)+'</h1><p>'+intro+'</p>'+chart+table(ds,list(ds[0]))+table(rows,['dataset','query','status','passed','duration_s','estimated_cost_usd'])+table(failures,['dataset','query','category','official_reason','semantic_root_cause']))
 def pct(v):return 'N/A' if v is None else f'{v:.2%}'
 md=['# '+title,'',intro,'',f'**Correct: {total["correct"]}/{total["scored"]} scored; unscored: {total["unscored"]}; coverage: {total["attempted"]}/104.**','',f'Dataset-macro Pass@1: {pct(total["dataset_macro_pass1"])}. Question-weighted accuracy: {pct(total["question_micro_accuracy"])}. Pass@5: unavailable.','',f'Recorded input tokens: {total["input_tokens"]:,}; cached input: {total["cached_input_tokens"]:,}; output: {total["output_tokens"]:,}; tool calls: {total["tool_calls"]:,}. Dollar cost: unavailable. Excluded attempts are accounted for separately in attempt-accounting.json.','','| Dataset | Scored | Correct | Accuracy | Unscored |','|---|---:|---:|---:|---:|']
 for d in ds:md.append(f'| {d["dataset"]} | {d["scored"]} | {d["correct"]} | {pct(d["accuracy"])} | {d["unscored"]} |')
 md += ['','## Failure review','',f'{sum((f["dataset"],f["query"]) in note_map for f in failures)} failed questions have selected trace-based reviews. This is not an exhaustive semantic adjudication. Official grades are unchanged. See failure_analysis.csv and review-notes.json for evidence.']
 for n in notes:
  md += ['',f'**{n["dataset"]}/query{n["query"]} — {n["category"]}:** '+n['evidence']]
 (dest/'report.md').write_text('\n'.join(md)+'\n');return total

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args();print(json.dumps(generate(a.out),indent=2))
