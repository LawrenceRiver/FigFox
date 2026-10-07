"""Remove only model-designated drafts after their SAM images have been bound."""
def apply_replacements(root):
    by_id={n.get('id'):n for n in root.iter() if n.get('id')}
    parents={c:p for p in root.iter() for c in p}
    plans=[];claimed=set();protected=set();unresolved=[]
    for node in root.iter():
        value=node.get('data-plus-replaces')
        if not value:continue
        images=[n for n in node.iter() if n.tag.rsplit('}',1)[-1]=='image']
        if not images or any(not (n.get('href') or '').startswith('data:image/png;base64,') for n in images):
            raise ValueError('replacement requires bound image assets')
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
            if not frames.issubset(covered):raise ValueError('frame coverage must be explicit')
            if not any(n.tag.rsplit('}',1)[-1] in {'path','rect','circle','ellipse','polygon','polyline','line','text','image','use'} for n in target.iter()):raise ValueError('empty replacement draft')
            claimed.add(oid)
        plans.append((node,targets))
    for oid in claimed:
        target=by_id[oid]
        if target.get('id') in protected:raise ValueError('replacement target is also explicitly kept')
        # A draft group can contain explicitly kept overlays. Preserve their
        # ancestor chain (and inherited transforms/styles), pruning only siblings.
        for kept in (n for n in target.iter() if n.get('id') in protected):
            ancestor=parents.get(kept)
            while ancestor is not None:
                if ancestor.tag.rsplit('}',1)[-1] not in ('g','svg'):
                    raise ValueError('cannot preserve kept descendant inside painted container')
                if ancestor is target:break
                ancestor=parents.get(ancestor)
        ancestor=parents.get(target)
        while ancestor is not None:
            if ancestor.get('id') in claimed:raise ValueError('overlapping replacement targets')
            ancestor=parents.get(ancestor)
    log=list(unresolved)
    def prune_unprotected(node):
        if node.get('id') in protected:return
        for child in list(node):
            if child.tag.rsplit('}',1)[-1] in ('defs','style','title','desc','metadata'):continue
            if any(n.get('id') in protected for n in child.iter()):prune_unprotected(child)
            else:node.remove(child)
    for node,targets in plans:
        removed=[];pruned=[]
        for oid in targets:
            if any(n.get('id') in protected for n in by_id[oid].iter()):
                prune_unprotected(by_id[oid]);pruned.append(oid)
            else:
                parents[by_id[oid]].remove(by_id[oid]);removed.append(oid)
        node.attrib.pop('data-plus-replaces')
        log.append({'replacement_id':node.get('id'),'removed_draft_ids':removed,'pruned_draft_ids':pruned,'kept_ids':node.get('data-plus-keeps','').split(),'covered_frame_ids':node.get('data-plus-covered-frames','').split()})
    return log
