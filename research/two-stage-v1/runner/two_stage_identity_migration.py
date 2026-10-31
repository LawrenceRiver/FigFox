"""Append-only identity migration for audited preparation-bridge fixes only."""
from copy import deepcopy
from pathlib import Path
import run_ablation as r,bounded_trace as trace

def verify(marker,expected,control):
 old=r.read(marker)
 projected=deepcopy(old);projected['initial_sha256']=expected.get('initial_sha256')
 if projected==expected and old.get('initial_sha256')!=expected.get('initial_sha256'):
  marker=Path(marker);sample=marker.parent.parent
  for path in sample.glob('A*/first-reference-migrations/*.json'):
   migration=r.read(path)
   if migration.get('format')!='duplicate-sam-alias-initial-migration-v1' or migration.get('original_svg_sha256')!=old['initial_sha256'] or migration.get('effective_svg_sha256')!=expected['initial_sha256']:continue
   for key in ('original_first_receipt','effective_first_receipt'):
    if r.sha(migration[key])!=migration[key+'_sha256']:raise ValueError('initial migration receipts changed')
   before=r.read(migration['original_first_receipt']);after=r.read(migration['effective_first_receipt'])
   if r.sha(before['stage0_scene'])!=old['initial_sha256'] or r.sha(after['stage0_scene'])!=expected['initial_sha256']:raise ValueError('initial SVG source binding changed')
   if r.sha(before['original'])!=expected['source_sha256'] or r.sha(after['original'])!=expected['source_sha256']:raise ValueError('initial source image changed')
   for first in (before,after):
    if r.sha(Path(first['stage0_scene']).parent/'preview.png')!=migration['identical_native_png_sha256']:raise ValueError('native rendered pixels changed')
   original_provenance=r.read(before['provenance']);effective_provenance=r.read(after['provenance'])
   if {k:v for k,v in original_provenance.items() if k!='initial_svg_sha256'}!={k:v for k,v in effective_provenance.items() if k!='initial_svg_sha256'}:raise ValueError('initial provenance/source/capabilities changed')
   proof=Path(after['stage0_scene']).parents[2]/'syntax-recovery.json';recovery=r.read(proof)
   if recovery.get('provider_calls_added')!=0 or recovery.get('source_prompt_and_images_verified') is not True:raise ValueError('verified zero HTTP native replay required')
   allowed={'source-bound frozen native parser supplies stable generic IDs before metadata scope checks; no geometry/style/text edit','remove byte-identical duplicate xlink asset alias; native SAM binding embeds the same unqualified href'}
   if any(x.get('operation') not in allowed for x in recovery['operations']):raise ValueError('alias migration cannot hide other initial edits')
   record={'format':'append-only-inactive-initial-alias-migration-v1','original_identity_sha256':r.sha(marker),'effective_identity':expected,'migration_file':str(path),'migration_sha256':r.sha(path),'original_identity_overwritten':False,'no_prior_native_artifacts':True,'identical_native_png_sha256':migration['identical_native_png_sha256']}
   destination=marker.parent/'identity-migrations'/('initial-'+expected['initial_sha256']+'.json')
   if destination.exists():
    previous=r.read(destination);normalized_previous=deepcopy(previous);normalized_record=deepcopy(record)
    for value in (normalized_previous,normalized_record):value['migration_file']=str(Path(value['migration_file']).resolve())
    if normalized_previous!=normalized_record:raise ValueError('initial migration conflict')
    if (marker.parent/'cell').exists() and r.sha(marker.parent/'cell/inputs/supplied-initial.svg')!=expected['initial_sha256']:raise ValueError('prepared native initial differs from audited migration')
   else:
    if (marker.parent/'cell').exists() or list(marker.parent.glob('native-forks/*/cell/runs/*/state.json')):raise ValueError('initial source cannot change after native preparation')
    trace.write(destination,record)
   return True
 for path in (Path(control)/'protocol-migrations').glob('*-bridge-migration.json'):
  migration=r.read(path)
  if old.get('bindings',{}).get('bridge')!=migration['from_sha256'] or expected.get('bindings',{}).get('bridge')!=migration['to_sha256']:continue
  if r.sha(migration['old_source_archive'])!=migration['from_sha256'] or r.sha(migration['new_source_archive'])!=migration['to_sha256']:raise ValueError('bridge migration source archive changed')
  projected=deepcopy(old);projected['bindings']['bridge']=migration['to_sha256']
  if projected!=expected:raise ValueError('migration cannot change source/capabilities/native flow/runtime or other identity fields')
  record={'format':'append-only-preparation-bridge-identity-migration-v1','original_identity_sha256':r.sha(marker),'effective_identity':expected,'migration_file':str(path),'migration_sha256':r.sha(path),'original_identity_overwritten':False,'native_artifacts_changed':False}
  destination=Path(marker).parent/'identity-migrations'/(migration['to_sha256']+'.json')
  if destination.exists() and r.read(destination)!=record:raise ValueError('identity migration conflict')
  if not destination.exists():trace.write(destination,record)
  return True
 raise ValueError('branch immutable binding mismatch; no exact audited bridge-only migration')
