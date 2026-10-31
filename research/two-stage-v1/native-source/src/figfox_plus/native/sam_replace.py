"""Remove only model-designated drafts after their SAM images have been bound."""
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

def _authenticated_crop(node,proof):
    if proof.get('node_id')!=node.get('id') or proof.get('representation') not in ('raster','vector'):return False
    if hashlib.sha256(ET.tostring(node)).hexdigest()!=proof.get('node_sha256'):return False
    try:
        return (hashlib.sha256(Path(proof['asset_path']).read_bytes()).hexdigest()==proof['asset_sha256']
                and hashlib.sha256(Path(proof['source_path']).read_bytes()).hexdigest()==proof['source_sha256'])
    except (OSError,KeyError,TypeError):return False

def apply_replacements(root,host_crops=None):
    host_crops={} if host_crops is None else host_crops
    by_id={n.get('id'):n for n in root.iter() if n.get('id')}
    parents={c:p for p in root.iter() for c in p}
    plans=[];claimed=set();protected=set();unresolved=[]
    for node in root.iter():
        value=node.get('data-plus-replaces')
        if not value:continue
        images=[n for n in node.iter() if n.tag.rsplit('}',1)[-1]=='image']
        proof=host_crops.get(node.get('id'))
        bound=bool(images) and all((n.get('href') or '').startswith('data:image/png;base64,') for n in images)
        if not (_authenticated_crop(node,proof) if proof is not None else bound):
            raise ValueError('replacement requires bound image assets or authenticated host crop')
        targets=value.split()
        keep=set(node.get('data-plus-keeps','').split());covered=set(node.get('data-plus-covered-frames','').split())
        if not keep.issubset(by_id):raise ValueError('unknown kept object')
        protected.update(keep)
        missing=[oid for oid in targets if oid not in by_id]
        if missing:
            unresolved.append({'replacement_id':node.get('id'),'status':'unresolved_missing_draft','missing_ids':missing,'removed_draft_ids':[]})
            continue
        for oid in targets:
            if oid not in by_id or oid in claimed:raise ValueError('invalid or duplicate replacement target: '+oid)
            target=by_id[oid]
            if target is root or node in list(target.iter()) or target in list(node.iter()):raise ValueError('replacement and draft must be separate')
            frames={n.get('id') for n in target.iter() if n.get('data-plus-kind')=='frame'}
            frames.update(fid for n in target.iter() for fid in n.get('data-plus-host-frame-ids','').split())
            if not frames.issubset(covered):raise ValueError('frame coverage must be explicit')
            if not any(n.tag.rsplit('}',1)[-1] in {'path','rect','circle','ellipse','polygon','polyline','line','text','image','use'} for n in target.iter()):raise ValueError('empty replacement draft')
            claimed.add(oid)
        plans.append((node,targets))
    for oid in claimed:
        target=by_id[oid]
        if any(n.get('id') in protected for n in target.iter()):raise ValueError('replacement would delete protected object')
        ancestor=parents.get(target)
        while ancestor is not None:
            if ancestor.get('id') in claimed:raise ValueError('overlapping replacement targets')
            ancestor=parents.get(ancestor)
    log=list(unresolved)
    for node,targets in plans:
        for oid in targets:parents[by_id[oid]].remove(by_id[oid])
        node.attrib.pop('data-plus-replaces')
        log.append({'replacement_id':node.get('id'),'removed_draft_ids':targets,'kept_ids':node.get('data-plus-keeps','').split(),'covered_frame_ids':node.get('data-plus-covered-frames','').split()})
    return log
