"""Auditable append-only recovery of unaccepted verifier schema errors.

The frozen Flow.accept and all its validators execute unchanged. Only role_path
selects the latest immutable correction, so report bytes and every native source
SHA always refer to the same actual model receipt. Original receipts stay intact.
"""
import hashlib,json,sys,uuid,importlib.util
from pathlib import Path
FIELDS=('resolved_ids','unresolved_ids','not_required','new_required_findings','new_uncertain_findings','protected_regressions')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text())
def freeze(path,data):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('x') as stream:json.dump(data,stream,ensure_ascii=False,indent=2)
def invalid_schema(report):return not isinstance(report,dict) or any(not isinstance(report.get(key),list) for key in FIELDS)
def original_path(root,run,round_number):return Path(root)/'runs'/run/('round-'+str(round_number))/'verifier'
def verifier_path(root,run,round_number):
 root=Path(root);original=original_path(root,run,round_number);selected=original
 for folder in sorted((original/'corrections').glob('[0-9]*')):
  metadata=folder/'correction.json'
  if not metadata.exists():raise ValueError('incomplete verifier correction; inspect preserved recovery record')
  binding=read(metadata)
  if binding['original_raw_sha256']!=sha(original/'raw.json') or binding['original_receipt_sha256']!=sha(original/'receipt.json'):raise ValueError('original verifier receipt changed')
  if binding['superseded_raw_sha256']!=sha(selected/'raw.json') or binding['native_flow_sha256']!=sha(root/'flow.py') or binding['recovery_runtime_sha256']!=sha(__file__):raise ValueError('verifier correction provenance mismatch')
  if binding['new_raw_sha256']!=sha(folder/'raw.json') or read(folder/'receipt.json')['sha256']!=sha(folder/'raw.json'):raise ValueError('verifier correction raw receipt changed')
  selected=folder
 return selected

def append_correction(root,run,round_number,source):
 root=Path(root);source=Path(source);original=original_path(root,run,round_number);selected=verifier_path(root,run,round_number)
 if read(root/'runs'/run/'state.json').get('last_round',0)>=round_number:raise ValueError('accepted verifier round cannot be corrected')
 if read(selected/'receipt.json')['sha256']!=sha(selected/'raw.json'):raise ValueError('old verifier raw hash mismatch')
 if not invalid_schema(read(selected/'raw.json')):raise ValueError('only schema-invalid unaccepted verifier receipts may be corrected; quality judgments cannot be superseded')
 if invalid_schema(read(source)):raise ValueError('new verifier model output still has invalid schema')
 candidate=root/'runs'/run/('round-'+str(round_number))/'candidate.json'
 if not candidate.is_file():raise ValueError('correction requires the existing native candidate')
 state=root/'runs'/run/'state.json';state_hash=sha(state);candidate_hash=sha(candidate)
 prior=list((original/'corrections').glob('[0-9]*'));folder=original/'corrections'/f'{len(prior)+1:04}';folder.mkdir(parents=True,exist_ok=False)
 raw=source.read_bytes()
 with (folder/'raw.json').open('xb') as stream:stream.write(raw)
 freeze(folder/'dispatch.json',{'agent_id':'api-verifier-correction-'+str(uuid.uuid4()),'role':'verifier','round':round_number,'original_dispatch_sha256':sha(original/'dispatch.json'),'fresh_model_role_context':True})
 freeze(folder/'receipt.json',{'agent_id':read(folder/'dispatch.json')['agent_id'],'sha256':sha(folder/'raw.json'),'source_file':str(source.resolve()),'correction_of_raw_sha256':sha(selected/'raw.json')})
 if sha(state)!=state_hash or sha(candidate)!=candidate_hash:raise ValueError('native state changed while registering correction')
 freeze(folder/'correction.json',{'format':'append-only-unaccepted-verifier-schema-correction-v1','original_raw_sha256':sha(original/'raw.json'),'original_receipt_sha256':sha(original/'receipt.json'),'superseded_raw_sha256':sha(selected/'raw.json'),'new_raw_sha256':sha(folder/'raw.json'),'native_flow_sha256':sha(root/'flow.py'),'recovery_runtime_sha256':sha(__file__),'state_sha256_before':state_hash,'candidate_sha256':candidate_hash,'source_model_output':str(source.resolve()),'reason':'schema-invalid unaccepted verifier receipt; no quality disposition rewritten','native_accept_validation':'required unchanged; correction registration is not acceptance'})
 return folder

def install(module):
 original=module.Flow
 class RecoveryFlow(original):
  def role_path(self,run,role,round_number=None):
   folder=super().role_path(run,role,round_number)
   return verifier_path(self.root,run,round_number) if role=='verifier' and (folder/'corrections').exists() else folder
 module.Flow=RecoveryFlow

def main():
 flow=Path(sys.argv[1]).resolve();sys.path.insert(0,str(flow.parent));args=sys.argv[2:]
 spec=importlib.util.spec_from_file_location('frozen_native_flow_with_audited_receipt_selection',flow);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);install(module)
 sys.argv=[str(flow),*args];module.main()
if __name__=='__main__':main()
