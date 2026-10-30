import unittest,importlib.util,json
from pathlib import Path
from report import summarize
from run import prompt,all_tasks
class ProtocolTests(unittest.TestCase):
 def test_macro_is_dataset_stratified_not_pooled(self):
  rows=[dict(dataset='small',query=1,trial=0,status='completed',grading_status='scored',passed=True)]
  rows += [dict(dataset='large',query=i,trial=0,status='completed',grading_status='scored',passed=False) for i in range(10)]
  total,ds=summarize(rows);self.assertEqual(total['dataset_macro_pass1'],.5);self.assertFalse(total['complete']);self.assertIsNone(total['pass5'])
 def test_infrastructure_is_not_an_incorrect_model_answer(self):
  rows=[dict(dataset='data',query=1,trial=0,status='runtime_error',grading_status='scored',passed=None)]
  t,_=summarize(rows);self.assertEqual(t['scored'],0);self.assertEqual(t['unscored'],1);self.assertIsNone(t['dataset_macro_pass1'])
 def test_duplicate_trials_rejected(self):
  r=dict(dataset='data',query=1,trial=0,status='completed',grading_status='scored',passed=True)
  with self.assertRaises(ValueError):summarize([r,r])
 def test_original_user_prompt_preserved_for_all_104_questions(self):
  roots=[Path('/home/minhyeok/dab-reproduction'),Path('/workspace/scratch/1d00d590a198/dab-source')]
  root=next((p for p in roots if p.exists()),None)
  if root is None:self.skipTest('Upstream unavailable')
  src=root/'common_scaffold/prompts/prompt_builder.py';spec=importlib.util.spec_from_file_location('original_prompt_builder',src);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  tasks=all_tasks(root);self.assertEqual(len(tasks),104)
  for d,q in tasks:
   ds=root/('query_'+d);v=json.loads((ds/f'query{q}/query.json').read_text());question=v if isinstance(v,str) else v['query']
   desc=(ds/'db_description.txt').read_text().strip()+'\n\n'+(ds/'db_description_withhint.txt').read_text().strip()
   self.assertEqual(prompt(root,d,q),m.init_messages(question,desc,'gpt-5.6-terra')[1]['content'],(d,q))
if __name__=='__main__':unittest.main()
