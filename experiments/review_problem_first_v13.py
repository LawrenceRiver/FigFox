"""Independent single-image reviews. Each image runs at the same time."""
import argparse
import json
from pathlib import Path
import traceback
from concurrent.futures import ThreadPoolExecutor,as_completed
from figfox_plus.native.review_problem_first_v13.orchestrator import prepare,run


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--bundle',required=True)
    parser.add_argument('--arrow-inputs',required=True)
    parser.add_argument('--out',required=True)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--workers',type=int,default=0)
    args=parser.parse_args()
    bundle=json.loads(Path(args.bundle).read_text())
    arrows=json.loads(Path(args.arrow_inputs).read_text())
    out=Path(args.out).resolve();out.mkdir(exist_ok=False,parents=True)
    cases=[]
    for name,im in bundle['images'].items():
        if not name.replace('-','').replace('_','').isalnum():raise ValueError('invalid case ID')
        root=out/name
        prepare({'images':{name:im}},root,upstream_arrow_specs={name:arrows.get(name)})
        cases.append((name,root));print(json.dumps({'case':name,'status':'prepared'}),flush=True)
    workers=len(cases) if args.workers==0 else args.workers
    if workers<1:raise ValueError('workers must be at least 1')
    (out/'experiment.json').write_text(json.dumps({'version':'review_problem_first_v13',
        'case_dirs':{k:str(p) for k,p in cases},'max_requests_per_image':2,
        'api_budget_seconds':240,
        'execution':'independent image contexts in parallel','workers':workers,'model':'deepseek-flash',
        'sol_requests':0},indent=2))
    if not args.execute:return
    def evaluate(case):
        name,root=case
        try:
            result=run(root,request_limit=2)
            summary={'case':name,'status':result['status'],
                'issue_records':len(result.get('issues',[])),
                'rcd_records':len(result.get('rcd',[])),
                'records_complete':result.get('coverage',{}).get('records_complete',False)}
        except Exception as exc:
            summary={'case':name,'status':'request_or_runtime_failed','error':str(exc)}
            # Preserve any completed phase and execution artifacts.
            (root/'run-error.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
            traceback.print_exc()
        return summary
    summaries=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(evaluate,case) for case in cases]
        for future in as_completed(futures):
            summary=future.result();summaries.append(summary)
            (out/'summary.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2))
            print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
