"""Provider-independent boundary. No network client or credentials bundled."""
from typing import Protocol
class JudgeAdapter(Protocol):
 def judge(self, request: dict) -> dict:
  """Return model-response.schema.json; transport/image encoding belong to caller."""
  ...
class MockAdapter:
 def judge(self, request: dict) -> dict:
  return {'task_id':request['task_id'],'source':'mock','findings':[
   {'item_id':item['item_id'],'unit_id':unit['id'],'status':'unknown','evidence':[],
    'reason':'MOCK ONLY: offline contract demonstration; no visual or editing judgment performed',
    'severity':'none','repair_scope':'unknown','root_cause':'mock:'+item['item_id']+':'+unit['id']}
   for item in request['items'] if item['applicability']['state']=='applicable' for unit in item['applicability']['units']]}
