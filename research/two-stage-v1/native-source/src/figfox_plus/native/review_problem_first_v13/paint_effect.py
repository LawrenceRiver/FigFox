"""Host structural certificates; these never certify visual or F clearance."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _tree(node):
    # Text, tails, order, unnamed nodes and every attribute are protected too.
    return [node.tag, sorted(node.attrib.items()), node.text, node.tail, [_tree(c) for c in node]]


def required(program, selected):
    categories = {q['category'] for q in selected}
    return ('F' in categories and 'E' not in categories
            and not any(r.get('predicate') in ('contain', 'separate') for r in program.get('relations', [])))


def eligible(program, selected, root, source):
    from .programs import _marked_cubic_fill_removal
    # The serial XML parser discards comments; reject rather than silently erase them.
    return (root is not None and isinstance(source, str) and '<!--' not in source and required(program, selected)
            and _marked_cubic_fill_removal(program, selected, root, source))


def _protected(root, targets):
    by = {n.get('id'): n for n in root.iter() if n.get('id')}
    parents = {c: n for n in root.iter() for c in n}
    geometry, context = [], []
    for target in targets:
        node = by[target]
        geometry.append([target, _tree(node)])
        chain = []
        current = node
        while current in parents:
            current = parents[current]
            chain.append([current.tag, sorted(current.attrib.items()), current.text, current.tail])
        marker = by[node.get('marker-end')[5:-1]]
        marker_chain = []
        current = marker
        while current in parents:
            current = parents[current]
            marker_chain.append([current.tag, sorted(current.attrib.items()), current.text, current.tail])
        context.append([target, chain, _tree(marker), marker_chain])
    styles = [_tree(n) for n in root.iter() if n.tag.rsplit('}', 1)[-1] == 'style']
    return {'protected_geometry_sha256': _hash(geometry), 'marker_context_sha256': _hash(context),
            'style_context_sha256': _hash(styles)}


def prove_transition(program, selected, before, after, source):
    """Independent exact comparison, followed by the strong context predicate."""
    if not eligible(program, selected, before, source):
        raise ValueError('current paint-effect predicate failed')
    expected = deepcopy(before)
    targets = sorted(program['target_ids'])
    by = {n.get('id'): n for n in expected.iter() if n.get('id')}
    changes = []
    for target in targets:
        changes.append({'target_id': target, 'attribute': 'fill', 'before': by[target].get('fill'), 'after': 'none'})
        by[target].set('fill', 'none')
    if _tree(expected) != _tree(after):
        raise ValueError('paint-effect postcondition failed: unexpected tree mutation')
    return {'version': 'paint-effect-v1', 'program_sha256': _hash(program), 'target_ids': targets,
            'pre_tree_sha256': _hash(_tree(before)), 'post_tree_sha256': _hash(_tree(after)),
            'changed_attributes': changes, **_protected(after, targets),
            'effective_fill': 'none', 'f_geometry_assessment': 'not_assessed', 'visual_acceptance': 'pending'}


def certificate(program, selected, before_path, after_path, before_revision, after_revision):
    before_source = Path(before_path).read_text()
    after_source = Path(after_path).read_text()
    for path, revision in ((before_path, before_revision), (after_path, after_revision)):
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != revision:
            raise ValueError('paint-effect certificate source revision mismatch')
    before = ET.fromstring(before_source)
    proof = prove_transition(program, selected, before, ET.fromstring(after_source), before_source)
    # The trees are now independently equal except fill. Also check raw post XML
    # for constructs discarded by ElementTree (comments, PIs, DTD declarations).
    if not eligible(program, selected, before, after_source):
        raise ValueError('paint-effect post source contains unsupported XML context')
    return dict(proof, before_svg=str(before_path), after_svg=str(after_path),
                before_revision=before_revision, after_revision=after_revision,
                status='valid', final_valid=False)


def audit(program, selected, proof, final_path, final_revision):
    """Rebuild historical proof and re-prove supported context in the final scene."""
    rebuilt = certificate(program, selected, proof['before_svg'], proof['after_svg'],
                          proof['before_revision'], proof['after_revision'])
    for key, value in rebuilt.items():
        if key not in ('status', 'final_valid') and proof.get(key) != value:
            raise ValueError('paint-effect certificate binding mismatch: ' + key)
    final_source = Path(final_path).read_text()
    if hashlib.sha256(Path(final_path).read_bytes()).hexdigest() != final_revision:
        raise ValueError('paint-effect final source revision mismatch')
    final = ET.fromstring(final_source)
    if _protected(final, proof['target_ids']) != {k: proof[k] for k in
            ('protected_geometry_sha256', 'marker_context_sha256', 'style_context_sha256')}:
        raise ValueError('paint-effect protected target/marker/style context changed')
    restored = deepcopy(final)
    by = {n.get('id'): n for n in restored.iter() if n.get('id')}
    for change in proof['changed_attributes']:
        node = by[change['target_id']]
        if node.get('fill') != 'none':
            raise ValueError('paint-effect effective fill no longer none')
        if change['before'] is None:
            node.attrib.pop('fill')
        else:
            node.set('fill', change['before'])
    if not eligible(program, selected, restored, final_source):
        raise ValueError('paint-effect final strong predicate failed')
    return {'final_revision': final_revision, 'final_tree_sha256': _hash(_tree(final)), 'final_valid': True}
