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
 models=sorted({r.get('model') for r in rows if r.get('model')})
 total={'model':models[0] if len(models)==1 else ','.join(models) or None,'attempted':len(rows),'expected':104,'datasets':len(ds),'expected_datasets':17,
        'complete':len(seen)==104 and len(ds)==17 and all(d['unscored']==0 for d in ds),
        'dataset_macro_pass1':statistics.mean(scores) if scores else None,'pass5':None,
        'scored':sum(d['scored'] for d in ds),'correct':sum(d['correct'] for d in ds),
        'unscored':sum(d['unscored'] for d in ds),'coverage_note':'Macro score is partial unless complete is true.',
        'estimated_cost_usd':sum(r['estimated_cost_usd'] for r in rows) if rows and all(r.get('estimated_cost_usd') is not None for r in rows) else None,
        'cost_note':'Pricing was not verified; estimated cost is unavailable. Token usage is retained; consult actual U-M Toolkit billing.'}
 if total['estimated_cost_usd'] is not None and str(total['model']).startswith('claude'):
  total['cost_note']='Claude Code total_cost_usd: client-side estimate, not billing. Anthropic Console usage is authoritative.'
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
 title=str(total['model'])+' DataAgentBench — '+('complete 104-task evaluation' if total['complete'] else 'partial evaluation')
 svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="950" height="{70+32*len(ds)}"><rect width="100%" height="100%" fill="white"/><text x="20" y="28" font-size="18">{html.escape(title)}</text>']
 for i,d in enumerate(ds):
  y=50+32*i;v=d['accuracy'];label='N/A' if v is None else f'{v:.1%}'
  svg.append(f'<text x="20" y="{y+17}">{html.escape(d["dataset"])}</text><rect x="230" y="{y}" width="{(v or 0)*540}" height="23" fill="#2563eb"/><text x="790" y="{y+17}">{label} ({d["scored"]} scored)</text>')
 svg.append('</svg>');chart=''.join(svg);(dest/'accuracy.svg').write_text(chart)
 def table(rs,columns):
  return '<table><thead><tr>'+''.join('<th>'+html.escape(k)+'</th>' for k in columns)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(str(r.get(k,'')))+'</td>' for k in columns)+'</tr>' for r in rs)+'</tbody></table>'
 harness=('Claude Code CLI harness (the paper evaluated Claude models with Claude Code); not the authors exact driver.' if str(total['model']).startswith('claude')
          else 'Authors native Codex driver was unavailable; this is a documented Codex CLI reconstruction.')
 intro='One independent trial per original question, descriptions+hints. Original query-specific validators. Pass@5 is not available. '+harness+' Offline/connection tests are excluded. Infrastructure failures are separate from wrong answers.'
 (dest/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>'+html.escape(title)+'</title><style>body{font:15px system-ui;margin:32px;color:#162236}table{border-collapse:collapse;margin:24px 0}th,td{border:1px solid #ddd;padding:8px}th{background:#edf2ff}svg{max-width:100%;height:auto}</style><h1>'+html.escape(title)+'</h1><p>'+intro+'</p>'+chart+table(ds,list(ds[0]))+table(rows,['dataset','query','status','passed','duration_s','estimated_cost_usd'])+table(failures,['dataset','query','category','official_reason','semantic_root_cause']))
 def pct(v):return 'N/A' if v is None else f'{v:.2%}'
 md=['# '+title,'',intro,'',f'**Correct: {total["correct"]}/{total["scored"]} scored; unscored: {total["unscored"]}; coverage: {total["attempted"]}/104.**','',f'Dataset-macro Pass@1: {pct(total["dataset_macro_pass1"])}. Question-weighted accuracy: {pct(total["question_micro_accuracy"])}. Pass@5: unavailable.','',f'Recorded input tokens: {total["input_tokens"]:,}; cached input: {total["cached_input_tokens"]:,}; output: {total["output_tokens"]:,}; tool calls: {total["tool_calls"]:,}. Dollar cost: unavailable. Excluded attempts are accounted for separately in attempt-accounting.json.','','| Dataset | Scored | Correct | Accuracy | Unscored |','|---|---:|---:|---:|---:|']
 for d in ds:md.append(f'| {d["dataset"]} | {d["scored"]} | {d["correct"]} | {pct(d["accuracy"])} | {d["unscored"]} |')
 md += ['','## Failure review','',f'{sum((f["dataset"],f["query"]) in note_map for f in failures)} failed questions have selected trace-based reviews. This is not an exhaustive semantic adjudication. Official grades are unchanged. See failure_analysis.csv and review-notes.json for evidence.']
 for n in notes:
  md += ['',f'**{n["dataset"]}/query{n["query"]} — {n["category"]}:** '+n['evidence']]
 (dest/'report.md').write_text('\n'.join(md)+'\n');return total

def pass_at_k(n,c,k):
 """Unbiased pass@k estimator (as in the DAB paper) for n trials with c correct."""
 if n-c<k:return 1.0
 p=1.0
 for i in range(n-c+1,n+1):p*=1-k/i
 return 1-p

def aggregate(trials,dest,labels=None):
 """Combine independent repeated sweeps of one model. Each trial is a directory with
 reports/runs.csv (or runs.csv). Nothing is re-graded or re-selected. A question that is not
 completed and scored in a trial (infrastructure failure, quota exhaustion) counts as unscored
 for that trial, never as wrong. Per-trial accuracy uses that trial's scored questions; cross-trial
 metrics (pass@n, consistency, SD) use only the questions scored in every trial ("common")."""
 trials=[Path(t) for t in trials];dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
 labels=labels or [t.name for t in trials];assert len(labels)==len(trials) and len(set(labels))==len(labels)
 per={}
 for t,name in zip(trials,labels):
  src=t/'reports/runs.csv' if (t/'reports/runs.csv').exists() else t/'runs.csv'
  with src.open() as f:rows=list(csv.DictReader(f))
  assert len(rows)==104 and len({(r['dataset'],r['query']) for r in rows})==104,'Incomplete or duplicated trial: '+str(t)
  per[name]={(r['dataset'],int(r['query'])):r for r in rows}
 keys=sorted(next(iter(per.values())));assert all(set(v)==set(keys) for v in per.values()),'Trials cover different questions'
 n=len(trials);models=sorted({r['model'] for rs in per.values() for r in rs.values()});assert len(models)==1,models
 datasets=sorted({d for d,q in keys})
 scored=lambda r:r['status']=='completed' and r.get('grading_status')=='scored' and r['passed'] in ('True','False')
 ok=lambda r:r['passed']=='True'
 common=[k for k in keys if all(scored(rs[k]) for rs in per.values())]
 def macro(f,ks):
  vals=[statistics.mean(f(k) for k in ks if k[0]==d) for d in datasets if any(k[0]==d for k in ks)]
  return statistics.mean(vals) if vals else None
 def sd(xs):return statistics.stdev(xs) if len(xs)>1 else 0.0
 trial_rows=[]
 for name,rs in per.items():
  sk=[k for k in keys if scored(rs[k])];num=lambda c:sum(int(float(rs[k].get(c) or 0)) for k in keys)
  trial_rows.append({'trial':name,'scored':len(sk),'unscored':len(keys)-len(sk),'correct':sum(ok(rs[k]) for k in sk),
                     'micro_accuracy':sum(ok(rs[k]) for k in sk)/len(sk) if sk else None,
                     'macro_pass1':macro(lambda k:ok(rs[k]),sk),'datasets_scored':len({k[0] for k in sk}),
                     'common_correct':sum(ok(rs[k]) for k in common),
                     'common_micro_accuracy':sum(ok(rs[k]) for k in common)/len(common) if common else None,
                     'common_macro_pass1':macro(lambda k:ok(rs[k]),common),
                     'input_tokens':num('input_tokens'),'cached_input_tokens':num('cached_input_tokens'),
                     'output_tokens':num('output_tokens'),'tool_calls':num('tool_calls'),
                     'median_duration_s':statistics.median(float(rs[k]['duration_s']) for k in sk) if sk else None,
                     'estimated_cost_usd':sum(float(rs[k]['estimated_cost_usd']) for k in keys) if all(rs[k].get('estimated_cost_usd') not in (None,'') for k in keys) else None})
 c={k:sum(ok(rs[k]) for rs in per.values() if scored(rs[k])) for k in keys}
 m={k:sum(scored(rs[k]) for rs in per.values()) for k in keys}
 questions=[{'dataset':d,'query':q,'scored_trials':m[(d,q)],'correct_trials':c[(d,q)],'common':(d,q) in common,
             **{f'{t}':(per[t][(d,q)]['passed'] if scored(per[t][(d,q)]) else 'unscored') for t in per}} for d,q in keys]
 ds=[]
 for d in datasets:
  ks=[k for k in keys if k[0]==d];cks=[k for k in common if k[0]==d]
  accs=[statistics.mean(ok(per[t][k]) for k in ks if scored(per[t][k])) for t in per if any(scored(per[t][k]) for k in ks)]
  ds.append({'dataset':d,'questions':len(ks),'mean_accuracy':statistics.mean(accs) if accs else None,'sd_accuracy':sd(accs),
             **{f'{t}':f"{sum(ok(per[t][k]) for k in ks if scored(per[t][k]))}/{sum(scored(per[t][k]) for k in ks)}" for t in per},
             'common_questions':len(cks),'all_trials_correct':sum(c[k]==n for k in cks),'no_trial_correct':sum(c[k]==0 for k in cks),
             'inconsistent':sum(0<c[k]<n for k in cks)})
 micro=[r['micro_accuracy'] for r in trial_rows if r['micro_accuracy'] is not None]
 mac=[r['macro_pass1'] for r in trial_rows if r['macro_pass1'] is not None]
 cmic=[r['common_micro_accuracy'] for r in trial_rows if r['common_micro_accuracy'] is not None]
 summary={'model':models[0],'trials':n,'trial_labels':labels,'questions':len(keys),'datasets':len(datasets),
          'complete_trials':sum(r['unscored']==0 for r in trial_rows),'common_questions':len(common),
          'common_datasets':len({k[0] for k in common}),
          'micro_accuracy_mean':statistics.mean(micro),'micro_accuracy_sd':sd(micro),
          'macro_pass1_mean':statistics.mean(mac),'macro_pass1_sd':sd(mac),
          'common_micro_accuracy_mean':statistics.mean(cmic) if cmic else None,'common_micro_accuracy_sd':sd(cmic),
          'common_macro_pass1_estimator':macro(lambda k:pass_at_k(n,c[k],1),common),
          f'common_macro_pass{n}':macro(lambda k:pass_at_k(n,c[k],n),common),
          f'common_micro_pass{n}':statistics.mean(c[k]>0 for k in common) if common else None,
          'all_trials_correct':sum(c[k]==n for k in common),'no_trial_correct':sum(c[k]==0 for k in common),
          'inconsistent':sum(0<c[k]<n for k in common),'per_trial':trial_rows,
          'note':('Per-trial accuracy uses that trial\'s scored questions; unscored (infrastructure/quota) questions are never counted wrong. '
                  'Cross-trial metrics use only questions scored in every trial. Macro averages questions within each dataset, then datasets '
                  '(paper stratification). SD is across trials.')}
 def csvwrite(name,rs):
  with (dest/name).open('w',newline='') as f:
   w=csv.DictWriter(f,fieldnames=list(rs[0]));w.writeheader();w.writerows(rs)
 csvwrite('trials.csv',trial_rows);csvwrite('questions.csv',questions);csvwrite('datasets.csv',ds)
 (dest/'summary.json').write_text(json.dumps({'summary':summary,'datasets':ds},indent=2)+'\n')
 return summary

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('out',type=Path,nargs='?');p.add_argument('--trials',nargs='+',type=Path);p.add_argument('--dest',type=Path)
 p.add_argument('--labels',nargs='+',default=None)
 a=p.parse_args()
 print(json.dumps(aggregate(a.trials,a.dest,a.labels) if a.trials else generate(a.out),indent=2))
