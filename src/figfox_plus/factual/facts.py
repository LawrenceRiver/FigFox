"""Generic factual handoff and native operation validation, no sample answers."""
from pathlib import Path
import copy
from . import contracts as C
NATIVE={'set','text','remove','append_svg','replace_svg','source_crop'}
def box(v,w,h):
 C.require(isinstance(v,list) and len(v)==4 and all(type(n) is int for n in v),'integer whole-image crop box required')
 l,t,r,b=v;C.require(0<=l<r<=w and 0<=t<b<=h,'fact crop outside image')
 return v

def validate_facts(value,w,h):
 C.validate_findings(value,w,h);facts=value.get('fact_inventory');C.require(isinstance(facts,list) and bool(facts),'compact source fact inventory required');ids=[]
 for f in facts:
  C.require(C.nonempty(f.get('id')) and f.get('region') in 'ABCD','fact identity required');ids.append(f['id'])
  C.require(f.get('kind') in {'literal','count','number','connection','geometry','layout'},'fact kind required')
  C.require(f.get('certainty') in {'clear','uncertain'} and C.nonempty(f.get('source_basis')),'source evidence/certainty required')
  C.require('source_reading' in f and 'initial_reading' in f,'independent readings required')
  box(f.get('source_box'),w,h);box(f.get('initial_box'),w,h)
 C.require(len(ids)==len(set(ids)),'duplicate fact ID')
 for req in value.get('detail_requests',[]):
  C.require(req.get('fact_id') in ids and C.nonempty(req.get('reason')),'detail crop bound to actual fact required');box(req.get('source_box'),w,h);box(req.get('initial_box'),w,h)
 return value

def validate_fact_checks(plan,findings):
 facts=findings['fact_inventory'];checks=plan.get('fact_checks',[])
 C.require(isinstance(checks,list) and len(checks)==len(facts) and {f['fact_id'] for f in checks}=={f['id'] for f in facts},'all source facts must be independently checked')
 for c in checks:
  C.require(c.get('decision') in {'confirmed','corrected','uncertain'} and C.nonempty(c.get('source_evidence')),'factual re-reading decision/evidence required')
  C.require('source_reading' in c and 'initial_reading' in c,'planner independent readings required')
 return plan

def effective_findings(findings,plan):
 result=copy.deepcopy(findings);extra=plan.get('additional_issues',[]);C.require(isinstance(extra,list),'additional issues list required')
 old={i['id'] for i in findings['issues']};C.require(all(i['id'] not in old for i in extra),'additional issues cannot overwrite original observations')
 result['issues'].extend(copy.deepcopy(extra))
 for region in result['regions']:
  if any(i['region']==region['id'] for i in extra):region['status']='differences'
 return result

def implementation(plan):
 txs=[]
 for tx in plan['transactions']:
  ops=tx['parameters'].get('operations');C.require(isinstance(ops,list) and bool(ops),'planner must provide complete native operations before direct execution')
  C.require(all(o.get('op') in NATIVE for o in ops),'no SVG Plus/TP or invented operation allowed')
  txs.append({'id':tx['id'],'edits':copy.deepcopy(ops),'implementation_notes':'Exact planner operations; deterministic local execution, no model transcribing step.'})
 return {'transactions':txs}
