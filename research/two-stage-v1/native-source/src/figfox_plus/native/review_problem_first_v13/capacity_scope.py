"""Strict revision/component scope admission before the legacy permissive selector."""
from copy import deepcopy
import re
import xml.etree.ElementTree as ET

from .capacity_merge import _scope, _svg_graph
from .capacity_program_contract import canonicalize_capacity_program
from .programs import _compile_typed_scope, _measurement_references, _walk_operations, normalize_relations
from .scene import descendants, digest


def _xml_references(node):
    refs=set()
    for element in node.iter():
        if element.tag.rsplit('}',1)[-1] in ('style','script','animate','animateTransform'):
            raise ValueError('returned dynamic/global SVG scope cannot be proven')
        for key,value in element.attrib.items():
            refs.update(re.findall(r'url\(\s*[\"\']?#([^\s)\"\']+)',value))
            if key.rsplit('}',1)[-1]=='href' and value.startswith('#'):refs.add(value[1:])
    return refs


def guard_program(raw, batch, components, images, namespace):
    """Keep raw values; only normalize identities after checking exact revision."""
    image=images.get(raw.get('image_id'))
    if image is None:raise ValueError('unknown image')
    if raw.get('base_revision')!=image['revision'] or digest(image['svg'])!=image['revision']:
        raise ValueError('exact base revision mismatch before selector')
    component=next((c for c in components if c['id']==raw.get('component_id') and c['id'] in batch['component_ids']),None)
    if component is None:raise ValueError('unknown assigned component')
    if not raw.get('issue_ids') or not set(raw['issue_ids'])<=set(component['issue_ids']):raise ValueError('program issue scope drift')
    program,log=canonicalize_capacity_program(raw,image['svg'],namespace)
    root=ET.parse(image['svg']).getroot();graph=_svg_graph(image['svg']);existing=set(graph[0])
    declared=set(program['target_ids'])
    if not declared or not declared<=existing:raise ValueError('unknown current target')
    allowed_writes=set(component['write_ids']);allowed_reads=allowed_writes|set(component['read_ids'])
    if not descendants(root,list(declared))<=allowed_writes:raise ValueError('declared write scope drift')
    reads=set(program.get('read_ids',[]));created=set();anchors=set()
    if program['route']=='module_program':
        compiled=_compile_typed_scope(program,root)
        created=set(compiled['created_ids'])
        if set(program.get('created_target_ids',[]))!=created:raise ValueError('created ID declaration does not match typed lifecycle')
        writes=set(compiled['existing_write_ids'])
        if not descendants(root,list(writes))<=allowed_writes:raise ValueError('compiled write scope drift')
        for op in list(_walk_operations(program['args']['operations']))+list(_walk_operations(program.get('convergence',{}).get('repairs',[]))):
            args=op['args']
            if op['method'] in ('measure','check_tp','sample_colors'):reads.update(op['target_ids'])
            # repair_toolbox._run_operation forwards these IDs to tp_v2.align,
            # whose reference selection is a current-scene read independent of
            # mutation target_ids and $measure expressions. Other current native
            # methods use their targets, literal numeric boxes, BP anchors or
            # SVG references handled below. Walked nested/convergence operations
            # have the same method contract as top-level operations.
            if op['method']=='tp_align':
                refs=args.get('reference_ids')
                if not isinstance(refs,list) or not refs or any(not isinstance(i,str) or not i for i in refs):
                    raise ValueError('tp_align requires literal nonempty reference_ids for provable read scope')
                reads.update(refs)
            reads.update(_measurement_references(args))
            for key in ('parent_id','before_id','after_id'):
                anchor=args.get(key)
                if anchor=='@parent':
                    parents={child:parent for parent in root.iter() for child in parent}
                    for target in op['target_ids']:
                        if target not in graph[0]:raise ValueError('created target needs explicit parent')
                        parent=parents.get(graph[0][target])
                        # An anonymous parent cannot be granted a named write scope.
                        if parent is None or not parent.get('id'):raise ValueError('unbounded anonymous parent insertion')
                        anchors.add(parent.get('id'))
                elif anchor is not None:anchors.add(anchor)
            if op['method']=='bp_add':
                reads.update(_xml_references(ET.fromstring('<g>'+args['svg']+'</g>')))
            if op['method']=='bp_patch':
                attributes=args.get('attributes',{})
                if not isinstance(attributes,dict):raise ValueError('patch attributes must be object')
                # An evaluated reference could introduce undeclared dependency.
                for key,value in attributes.items():
                    if key in ('href','fill','stroke','filter','clip-path','mask','marker-start','marker-mid','marker-end','style') or key.endswith('}href'):
                        if not isinstance(value,(str,int,float)):raise ValueError('dynamic SVG reference cannot prove scope')
                node=ET.Element('g',{k:str(v) for k,v in attributes.items() if isinstance(v,(str,int,float))})
                reads.update(_xml_references(node))
        if not anchors<=allowed_writes|created:raise ValueError('insertion anchor write scope drift')
        writes.update(anchors-created)
    else:
        if program.get('created_target_ids'):raise ValueError('opaque generated created IDs cannot be proven')
        writes=declared;reads.update(existing)
    # Use the same original relation normalization and expression reference
    # extraction as validate_programs, before that selector can rebind revision.
    copy=deepcopy(program)
    nested=copy.get('convergence',{}).get('relations',[])
    copy.setdefault('relations',[]).extend(nested)
    normalize_relations(copy,component['issues'])
    for rule in copy['relations']:
        reads.update([rule.get('subject_id'),rule.get('object_id')])
    reads.update(_measurement_references(copy.get('convergence',{})))
    for check in copy.get('convergence',{}).get('alignment_checks',[]):
        reads.update(check.get('target_ids',[]));reads.update(check.get('reference_ids',[]))
    if not reads<=existing|created:raise ValueError('returned read references unknown current or created ID')
    # References also bring their subtree, inherited attributes and transitive
    # SVG definitions. New references cannot widen the component after DS2.
    actual_writes,actual_reads,unknown=_scope({'target_ids':sorted(writes),'read_ids':sorted(reads-created)},graph)
    if not actual_writes<=allowed_writes or not actual_reads<=allowed_reads:raise ValueError('returned write/read scope drift')
    if unknown and not component['unknown_scope']:raise ValueError('returned unknown scope')
    return program,log,{'component_id':component['id'],'write_ids':sorted(actual_writes),'read_ids':sorted(actual_reads),'created_ids':sorted(created),'base_revision':image['revision']}


def dependency_order(programs):
    """Stable topological order plus unresolved/cyclic programs, without dropping independent work."""
    by={p['id']:p for p in programs}
    if len(by)!=len(programs):raise ValueError('duplicate namespaced program ID')
    pending=list(programs);ordered=[];seen=set()
    while pending:
        ready=[p for p in pending if set(p.get('depends_on',[]))<=seen]
        if not ready:return ordered,pending
        for program in ready:
            ordered.append(program);seen.add(program['id']);pending.remove(program)
    return ordered,[]
