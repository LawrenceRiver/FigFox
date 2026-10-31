"""Source-bound proof of successful real SAM execution with zero eligible assets."""
import json,hashlib,struct
from pathlib import Path

def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def build(catalog,validation,original):
 catalog=Path(catalog).resolve();validation=Path(validation).resolve();original=Path(original).resolve();full=read(catalog);evidence=Path(full['catalog_path']).resolve();raw=evidence.parent/'sam/response.raw.json';regions=evidence.parent/'sam/raw_regions.json'
 proof={'format':'real-empty-sam-execution-v1','original_png_sha256':sha(original),'files':{key:{'path':str(path),'sha256':sha(path)} for key,path in [('catalog',catalog),('validation',validation),('evidence_catalog',evidence),('raw_response',raw),('raw_regions',regions)]}}
 verify(proof,original);return proof

def verify(proof,original):
 original=Path(original).resolve()
 if not isinstance(proof,dict) or proof.get('format')!='real-empty-sam-execution-v1' or proof.get('original_png_sha256')!=sha(original):raise ValueError('empty SAM requires source-bound real execution proof')
 files=proof.get('files',{})
 if set(files)!={'catalog','validation','evidence_catalog','raw_response','raw_regions'}:raise ValueError('complete empty-SAM receipt closure required')
 paths={}
 for key,record in files.items():
  path=Path(record['path'])
  if not path.is_absolute() or not path.is_file() or sha(path)!=record.get('sha256'):raise ValueError('SAM proof file changed or missing')
  paths[key]=path.resolve()
 full=read(paths['catalog']);validation=read(paths['validation']);evidence=read(paths['evidence_catalog']);raw=read(paths['raw_response']);regions=read(paths['raw_regions'])
 if full.get('source_hash')!=sha(original) or full.get('mock') is not False or full.get('config',{}).get('mock') is not False or full.get('status',{}).get('sam')!='ok' or full.get('assets')!=[]:raise ValueError('empty catalog is not a successful real source-bound SAM run')
 if Path(full['catalog_path']).resolve()!=paths['evidence_catalog'] or paths['raw_response']!=paths['evidence_catalog'].parent/'sam/response.raw.json' or paths['raw_regions']!=paths['raw_response'].with_name('raw_regions.json'):raise ValueError('SAM receipt closure path mismatch')
 if evidence.get('schema')!='figfox.shared_evidence_catalog.v1' or evidence.get('original_sha256')!=sha(original) or evidence.get('assets')!=[]:raise ValueError('empty evidence catalog provenance mismatch')
 argv=validation.get('argv',[])
 if validation.get('returncode')!=0 or len(argv)<2 or Path(argv[-2]).resolve()!=paths['catalog'] or Path(argv[-1]).resolve()!=original or not any('first_stage.validate_sam(' in str(arg) for arg in argv):raise ValueError('trusted source-bound SAM validation receipt required')
 png=original.read_bytes()
 if png[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('source PNG required')
 width,height=struct.unpack('>II',png[16:24])
 if evidence.get('image_size')!=[width,height] or raw.get('image',{}).get('width')!=width or raw.get('image',{}).get('height')!=height or raw.get('raw_regions')!=[] or raw.get('regions')!=[] or regions!=[] or not isinstance(raw.get('job_id'),str) or not raw['job_id']:raise ValueError('actual zero-region SAM response and source dimensions required')
 return True
