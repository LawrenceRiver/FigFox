import xml.etree.ElementTree as ET

from PIL import Image
import pytest

from figfox_plus.native.document import parse, serialize, measure
from figfox_plus.native.repair_toolbox import execute_batch
from figfox_plus.native.single_call.qlist import BY_ID


def scene():
    return parse('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="100" viewBox="0 0 120 100">'
        '<defs><marker id="shared" viewBox="0 0 6 6" refX="6" refY="3" markerWidth="6" markerHeight="6" orient="auto">'
        '<path id="tip" d="M0,0 L6,3 L0,6 Z" fill="red"/></marker></defs>'
        '<g id="target" transform="translate(20,20)"><rect id="frame" width="60" height="45" fill="white" stroke="black"/></g>'
        '<path id="neighbor" d="M90,75 L110,75" stroke="blue" marker-end="url(#shared)"/></svg>')


def issue(fragment):
    return {'id':'add-arrow','types':BY_ID['D']['legacy_types'],
        'description':'The synthetic arrow is missing.','original_evidence':'Original fixture arrow reference.',
        'target_ids':['target'],'neighbor_ids':['neighbor'],'operations':[
            {'method':'bp_add','target_ids':['target'],'args':{'parent_id':'target','svg':fragment}}]}


@pytest.mark.integration
def test_bp_add_can_read_existing_marker_without_modifying_shared_definition_or_consumer(tmp_path):
    root=scene();by={n.get('id'):n for n in root.iter() if n.get('id')}
    protected={oid:ET.tostring(by[oid]) for oid in ('shared','tip','neighbor')}
    original=tmp_path/'source.png';Image.new('RGB',(120,100),'white').save(original)
    before=serialize(root)
    report=execute_batch(root,[issue('<path id="new_arrow" d="M30,30 L60,40" stroke="red" fill="none" marker-end="url(#shared)"/>')],original,tmp_path/'repair')
    assert report['issues'][0]['status']=='applied',report
    assert serialize(root)!=before
    after={n.get('id'):n for n in root.iter() if n.get('id')}
    for oid,value in protected.items():assert ET.tostring(after[oid])==value
    measure(root,tmp_path/'render.png')
    with Image.open(tmp_path/'render.png') as image:assert image.size==(120,100)


@pytest.mark.integration
@pytest.mark.parametrize('fragment',[
    '<path id="new_arrow" d="M30,30 L60,40" marker-end="url(#unknown)"/>',
    '<path id="new_arrow" d="M30,30 L60,40" marker-end="url(https://example.invalid/marker.svg#shared)"/>',
    '<path id="new_arrow" d="M30,30 L60,40" onload="alert(1)" marker-end="url(#shared)"/>',
])
def test_bp_add_rejects_missing_ids_external_resources_and_active_content_transactionally(tmp_path,fragment):
    root=scene();before=serialize(root)
    original=tmp_path/'source.png';Image.new('RGB',(120,100),'white').save(original)
    report=execute_batch(root,[issue(fragment)],original,tmp_path/'repair')
    assert report['issues'][0]['status']!='applied'
    assert serialize(root)==before
