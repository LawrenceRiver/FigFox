import argparse,csv,json,sys
from pathlib import Path
from .engine import strict_json,evaluate,prepare_request,merge_response
from .adapters import MockAdapter

def main():
 p=argparse.ArgumentParser(description='FigFox v2 offline handoff; no API calls')
 p.add_argument('command',choices=['evaluate','prepare','mock','import-response']);p.add_argument('input');p.add_argument('--response');p.add_argument('--out',required=True);p.add_argument('--csv')
 a=p.parse_args()
 try:
  ip=Path(a.input);d=strict_json(ip);base=ip.resolve().parent
  if a.command=='prepare':out=prepare_request(d,base)
  elif a.command=='mock':out=MockAdapter().judge(prepare_request(d,base))
  elif a.command=='import-response':
   if not a.response:raise ValueError('--response required')
   out=merge_response(evaluate(d,base),strict_json(a.response),d)
  else:out=evaluate(d,base)
  path=Path(a.out);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
  if a.csv:
   if 'items' not in out:raise ValueError('--csv only supported for evaluation results')
   with Path(a.csv).open('w',newline='',encoding='utf-8-sig') as f:
    fields=['item_id','unit_id','status','score','source','verification','severity','repair_scope','reason','evidence','issue_id']
    w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader()
    for item in out['items']:
     for u in item['units'] or [dict(item_id=item['item_id'],status=item['status'])]:w.writerow(u)
  print(json.dumps({'output':str(path),'usability':out.get('usability'),'mode':out.get('mode',a.command)},ensure_ascii=False))
 except (ValueError,OSError,KeyError) as e:
  print('Rejected: '+str(e),file=sys.stderr);return 2
 return 0
if __name__=='__main__':sys.exit(main())
