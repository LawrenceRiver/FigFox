"""Strict cell assignment; availability never inferred from missing artifacts."""
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate assignment key: '+key)
        result[key]=value
    return result


def _read(path):
    return json.loads(path.read_text(),object_pairs_hook=_object)


def load(root):
    root=Path(root)
    record=_read(root/'inputs/capabilities.json')
    if not isinstance(record,dict) or set(record)!={'policy','sha256'}:
        raise ValueError('capability record requires policy and sha256')
    p=record['policy']
    if not isinstance(p,dict) or set(p)!={'version','sam','code_methods'} or p['version']!='capabilities-v1' or any(type(p[k]) is not bool for k in ('sam','code_methods')):
        raise ValueError('capability assignment requires strict SAM and code booleans')
    if record['sha256']!=digest(p):raise ValueError('capability hash mismatch')
    assignment=_read(root/'inputs/observer-assignment.json')
    expected={'format':'observer-assignment-v1','mode':'enabled' if p['code_methods'] else 'disabled_by_assignment','capability_sha256':digest(p)}
    if assignment!=expected:raise ValueError('observer assignment inconsistent with capability')
    if p['sam'] and (root/'inputs/sam.json').exists():
        enabled_catalog=_read(root/'inputs/sam.json')
        if isinstance(enabled_catalog,dict) and (enabled_catalog.get('format')=='sam-disabled-catalog-v1' or enabled_catalog.get('status')=='disabled_by_assignment'):
            raise ValueError('SAM enabled: catalog explicitly disabled by assignment')
    if not p['sam']:
        catalog=root/'inputs/sam.json'
        expected_catalog={'format':'sam-disabled-catalog-v1','status':'disabled_by_assignment','assets':[],'missing_assets':[],'complete_available_catalog':True}
        if catalog.is_symlink() or not catalog.is_file():
            raise ValueError('SAM disabled: explicit neutral catalog required')
        value=_read(catalog)
        if value!=expected_catalog or value.get('complete_available_catalog') is not True:
            raise ValueError('SAM disabled: contradictory neutral catalog')
        # No external SAM evidence at any input or run stage. Source crops and
        # embedded bitmaps are not SAM evidence and remain governed by code policy.
        forbidden={'sam','sam.json','sam-ledger.jsonl','arrow-head-evidence.json','first-sam-boards'}
        for base in (root/'inputs',root/'runs'):
            for artifact in base.rglob('*'):
                if artifact==catalog:continue
                if artifact.name in forbidden or artifact.name.startswith(('sam-','sam_')):
                    raise ValueError('SAM disabled: active artifact: '+str(artifact.relative_to(root)))
    if not p['code_methods']:
        for relative in ('analysis','observation-preparation-start.json','observation-build-timing.json','connector-paint-policy.json','connector-paint-preparation-start.json'):
            if (root/'inputs'/relative).exists():raise ValueError('disabled observer has active artifact: '+relative)
        for run in ('run1','run2','run3'):
            for n in (1,2,3):
                for name in ('connector-paint','connector-paint-start.json','connector-paint-registration-receipt.json','connector-paint-timing.json','connector-paint-native-timing.jsonl'):
                    if (root/'runs'/run/f'round-{n}'/name).exists():raise ValueError('disabled connector has active artifact: '+name)
    return dict(p)


def disabled(root):
    return not load(root)['code_methods']
