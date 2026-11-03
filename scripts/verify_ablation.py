"""Verify a portable ablation archive without network or model requests."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def verify(root,replay=False):
    root=Path(root).resolve();inventory=json.loads((root/'manifests/files.json').read_text())
    for record in inventory:
        path=root/record['path']
        if not path.is_relative_to(root) or not path.is_file() or sha(path)!=record['sha256']:raise ValueError('artifact mismatch: '+record['path'])
    rows=json.loads((root/'manifests/samples.json').read_text())
    if len(rows)!=240 or len({r['sample'] for r in rows})!=80:raise ValueError('expected 80 images and 240 configurations')
    score_count=0
    for row in rows:
        data=json.loads((root/row['receipt']).read_text())
        for k,h in [('source','source_sha256'),('initial','initial_sha256'),('final','final_sha256'),('png','png_sha256')]:
            if sha(root/data[k])!=data[h]:raise ValueError('lineage mismatch')
        scores=json.loads((root/data['scores18']).read_text())
        if len(scores)!=2 or len({s['request_id'] for s in scores})!=2:raise ValueError('independent receipts required')
        for s in scores:
            if len(s['items'])!=18 or {x['id'] for x in s['items']}!={f'D{i:02}' for i in range(1,19)}:raise ValueError('historical receipt incomplete')
        projected=json.loads((root/data['scores17']).read_text())
        for old,new in zip(scores,projected):
            expected=[dict(x,id=f"D{int(x['id'][1:])-(int(x['id'][1:])>15):02}") for x in old['items'] if x['id']!='D15']
            if new['items']!=expected:raise ValueError('17-criterion projection changed judgment')
        if data['configuration']=='C':
            a=json.loads((root/f"results/{row['sample']}/A/receipt.json").read_text())
            if a['initial_sha256']!=data['initial_sha256']:raise ValueError('A/C draft mismatch')
        elif replay:
            sys.path.insert(0,str(root/'code/src'))
            from figfox_plus.factual.contracts import apply_edits
            impl=json.loads((root/data['implementation']).read_text());ops=[x for tx in impl['transactions'] for x in tx['edits']]
            text,journal=apply_edits((root/data['initial']).read_text(),ops,root/data['source'])
            if text!=(root/data['final']).read_text() or len(journal)!=data['native_acceptance']['executed_operations']:raise ValueError('native replay mismatch')
        score_count+=2
    return {'images':80,'configurations':240,'historical_score_receipts':score_count,'files':len(inventory),'native_replay':replay}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('root');parser.add_argument('--replay',action='store_true');a=parser.parse_args();print(json.dumps(verify(a.root,a.replay),indent=2))
