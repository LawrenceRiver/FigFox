"""Scene identity and atomic, rendered checkpoint creation."""
from copy import deepcopy
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET
from ..document import validate, serialize, measure


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def descendants(root,targets):
    found={n.get('id'):n for n in root.iter() if n.get('id')}
    if any(t not in found for t in targets):raise ValueError('unknown target identity')
    return {n.get('id') for t in targets for n in found[t].iter() if n.get('id')}


def assert_target_scope(before,after,targets):
    """A generated constructor may alter target subtrees, never their surroundings."""
    validate(after)
    def global_styles(root):
        return [ET.tostring(n,encoding="unicode") for n in root.iter() if n.tag.rsplit("}",1)[-1]=="style"]
    if global_styles(before)!=global_styles(after):raise ValueError("generated code cannot alter global styles from a target subtree")
    if before.get('id') in targets:raise ValueError('whole SVG target scope unsupported')
    descendants(before,targets);descendants(after,targets)
    def masked(node):
        if node.get('id') in targets:return ('target',node.get('id'))
        return (node.tag,tuple(sorted(node.attrib.items())),(node.text or '').strip(),(node.tail or '').strip(),tuple(masked(n) for n in node))
    if masked(before)!=masked(after):raise ValueError('generated code modified outside target scope')


def write_checkpoint(root,folder,index):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    validate(root)
    svg=folder/f'scene-{index:04d}.svg';png=folder/f'scene-{index:04d}.png'
    # Render before committing identity; a render failure never changes active scene.
    measurement=measure(root,png)
    if not png.is_file():raise ValueError('renderer did not produce PNG')
    svg.write_text(serialize(root), encoding='utf-8')
    return {'svg':str(svg.resolve()),'png':str(png.resolve()),'revision':digest(svg)},measurement
