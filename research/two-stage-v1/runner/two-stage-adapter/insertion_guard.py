"""Common XML transaction proof; no geometry inference, providers or native edits."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
import re
from pathlib import Path
import xml.etree.ElementTree as ET


def digest(data):
    return hashlib.sha256(data if isinstance(data,bytes) else data.encode()).hexdigest()


def parse(text):
    inspected=re.sub(r'^\s*<\?xml\s[^?]*\?>','',text,count=1)
    if '<!' in inspected or '<?' in inspected:
        raise ValueError('insertion guard: declarations/comments/processing instructions unsupported')
    return ET.fromstring(text,parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True)))


def identities(root):
    rows=[n.get('id') for n in root.iter() if n.get('id') is not None]
    if any(not value for value in rows) or len(rows)!=len(set(rows)):
        raise ValueError('insertion guard: empty or duplicate ID')
    return {n.get('id'):n for n in root.iter() if n.get('id')}


def rights(program,issues,root):
    by_id=identities(root)
    selected=[row for row in issues if row['id'] in program['issue_ids']]
    if len(selected)!=len(set(program['issue_ids'])):raise ValueError('insertion guard: ambiguous linked issues')
    absent=[row for row in selected if row.get('target_ids')==[] and row.get('container_id')]
    if not absent:return None
    anchors=[row['container_id'] for row in absent]
    targets=[target for row in selected if row.get('target_ids') for target in row['target_ids']]
    if any(not isinstance(x,str) or x not in by_id for x in anchors+targets):
        raise ValueError('insertion guard: exact current anchor/target missing; aliases forbidden')
    if root.get('id') in anchors+targets:raise ValueError('insertion guard: root anchor/target unsupported')
    return {'anchors':sorted(set(anchors)),'existing_targets':sorted(set(targets)),'missing_issue_ids':[row['id'] for row in absent]}


def bind(programs,issues,svg):
    root=parse(Path(svg).read_text());bindings={}
    sources={}
    for index,p in enumerate(programs):
        if p.get('route')=='generated_python':sources.setdefault(p.get('source_code'),[]).append(index)
        permission=rights(p,issues,root)
        if permission:bindings[index]={'program':deepcopy(p),**permission}
    for index,binding in bindings.items():
        p=binding['program']
        if p['route']=='generated_python' and (not isinstance(p.get('source_code'),str) or len(sources[p['source_code']])!=1):
            raise ValueError('insertion guard: ambiguous exact program source binding')
    return bindings


def dependency_proof(before,fresh_ids,anchors,existing_targets,authorized_nodes):
    """Small explicit local-reference/static-CSS grammar, not a browser resolver."""
    by_id=identities(before);parents={c:p for p in before.iter() for c in p}
    affected=set()
    for ident in set(anchors)|set(existing_targets):
        node=by_id[ident]
        affected.update(n.get('id') for n in node.iter() if n.get('id'))
        while node is not None:
            if node.get('id'):affected.add(node.get('id'))
            node=parents.get(node)
    references=[];static_rules=0;png_images=0
    def reject(reason):raise ValueError('insertion guard: unsupported reference/style dependency: '+reason)
    ident_pattern=r'[A-Za-z_][A-Za-z0-9_.:-]*'
    url_pattern=re.compile(r'url\(\s*([\'\"]?)#('+ident_pattern+r')\1\s*\)',re.I)
    numeric=r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?(?:%|deg|grad|rad|turn)?'
    color_pattern=re.compile(r'(?:rgb|rgba|hsl|hsla)\((?:'+numeric+r'|[\s,/])+\)',re.I)
    def ref(value):
        if not re.fullmatch(ident_pattern,value):reject('unknown local reference syntax')
        if value in fresh_ids:reject('fresh ID captures preexisting reference '+value)
        if value in affected:reject('reference target lies in affected subtree/context '+value)
        references.append(value)
    def value(text,check_functions=False):
        if '\\' in text or '@' in text or re.search(r'\b(?:var|env|attr|expression)\s*\(',text,re.I):reject('escaped/dynamic value')
        def replace(match):ref(match.group(2));return ''
        cleaned=url_pattern.sub(replace,text)
        if re.search(r'\burl\b',cleaned,re.I):reject('nonlocal or unsupported URL')
        if check_functions:
            cleaned=color_pattern.sub('',cleaned)
            if '(' in cleaned or ')' in cleaned:reject('unsupported functional paint value')
    properties={'fill','fill-opacity','fill-rule','stroke','stroke-opacity','stroke-width','stroke-linecap','stroke-linejoin','stroke-miterlimit','stroke-dasharray','stroke-dashoffset','opacity','color','font-family','font-size','font-style','font-weight','font-stretch','font-variant','text-anchor','dominant-baseline','alignment-baseline','baseline-shift','letter-spacing','word-spacing','text-decoration','paint-order','vector-effect','visibility','display','shape-rendering','text-rendering','image-rendering','color-interpolation','color-interpolation-filters','clip-rule','clip-path','mask','filter','marker','marker-start','marker-mid','marker-end','cursor','stop-color','stop-opacity','flood-color','flood-opacity','lighting-color'}
    def declarations(text):
        if any(x in text for x in ('{','}','\\','@','/*','*/')):reject('unsupported declaration context')
        for declaration in text.split(';'):
            if not declaration.strip():continue
            if ':' not in declaration:reject('malformed declaration')
            key,content=declaration.split(':',1);key=key.strip().lower()
            if key not in properties or not content.strip():reject('unknown static CSS property')
            content=re.sub(r'\s*!important\s*$','',content,flags=re.I)
            value(content,True)
    compound=re.compile(r'(?:[A-Za-z_][A-Za-z0-9_-]*|\*)?(?:[.#][A-Za-z_][A-Za-z0-9_-]*)*')
    def stylesheet(text):
        nonlocal static_rules
        if any(x in text for x in ('\\','@','/*','*/')):reject('unsupported stylesheet context')
        position=0
        rule=re.compile(r'\s*([^{}]+)\{([^{}]*)\}')
        while position<len(text):
            if not text[position:].strip():break
            match=rule.match(text,position)
            if not match:reject('malformed stylesheet')
            for selector in match.group(1).split(','):
                parts=selector.split()
                if not parts or any(not part or not compound.fullmatch(part) for part in parts):reject('structural/pseudo/unknown selector')
            declarations(match.group(2));static_rules+=1;position=match.end()
    active={'script','link','foreignObject','animate','animateTransform','animateMotion','set','mpath'}
    paint_attributes=properties-{'font-family'}
    for node in before.iter():
        if node in authorized_nodes:continue
        tag=node.tag.rsplit('}',1)[-1] if isinstance(node.tag,str) else ''
        if tag in active:reject('active existing SVG context')
        if tag=='style':stylesheet(node.text or '')
        for key,text in node.attrib.items():
            key=key.rsplit('}',1)[-1].lower()
            if key=='href':
                if tag=='image' and text.startswith('data:image/png;base64,'):
                    # Protected image bytes/href are separately XML-invariant;
                    # embedded PNG has no SVG fragment-ID binding semantics.
                    png_images+=1;continue
                if text.startswith('#'):ref(text[1:]);continue
                reject('external/unsupported href')
            if key=='style':declarations(text)
            else:value(text,key in paint_attributes)
    return {'affected_existing_ids':sorted(affected),'preexisting_local_references':sorted(set(references)),'static_css_rule_count':static_rules,'unchanged_embedded_png_count':png_images,'grammar':'local-fragment-and-static-descendant-css-v1'}


def prove(before_text,after_text,anchors,existing_targets):
    before=parse(before_text);after=parse(after_text)
    old=identities(before);new=identities(after)
    if any(x not in old or x not in new for x in anchors):raise ValueError('insertion guard: missing anchor')
    if any(x not in old for x in existing_targets):raise ValueError('insertion guard: unknown existing target')
    if before.get('id') in set(anchors)|set(existing_targets):raise ValueError('insertion guard: root scope unsupported')
    inserted=[]
    safe={'g','path','rect','circle','ellipse','line','polyline','polygon','text','tspan','image'}
    # Global styles/resources are invariant even inside an independently writable target.
    global_tags={'style','defs','script','link','foreignObject','animate','animateTransform','animateMotion','set','linearGradient','radialGradient','stop','marker','pattern','clipPath','mask','filter','symbol','solidColor','hatch','hatchpath','meshgradient','meshrow','meshpatch','font','font-face','glyph','missing-glyph','color-profile','cursor','view','mpath'}
    def resource(node):
        if not isinstance(node.tag,str):return True
        tag=node.tag.rsplit('}',1)[-1]
        return tag in global_tags or tag.startswith('fe')
    def globals_(root):
        return [ET.tostring(n,encoding='unicode') for n in root.iter() if resource(n)]
    if globals_(before)!=globals_(after):raise ValueError('insertion guard: global style/resource change')
    def fresh(node):
        if not node.get('id') or node.get('id') in old:raise ValueError('insertion guard: inserted root needs fresh ID')
        for n in node.iter():
            if n.get('id') in old:raise ValueError('insertion guard: borrowed existing ID')
            if not isinstance(n.tag,str) or n.tag.rsplit('}',1)[-1] not in safe:raise ValueError('insertion guard: unsafe new element')
            if n.tag.startswith('{') and not n.tag.startswith('{http://www.w3.org/2000/svg}'):
                raise ValueError('insertion guard: foreign namespace')
            if any(k.rsplit('}',1)[-1].lower().startswith('on') for k in n.attrib):raise ValueError('insertion guard: event attribute')
            if any('@import' in v.lower() or 'javascript:' in v.lower() for v in n.attrib.values()):raise ValueError('insertion guard: active attribute')
        if node.tail not in (None,''):raise ValueError('insertion guard: fresh root tail changes surrounding text')
        inserted.append(node.get('id'))
    authorized_nodes={n for ident in existing_targets for n in old[ident].iter()}
    authorized_ids={n.get('id') for n in authorized_nodes if n.get('id')}
    if any(resource(n) for n in authorized_nodes):
        raise ValueError('insertion guard: existing-target subtree contains global resource/context')
    dependency=dependency_proof(before,set(new)-set(old),anchors,existing_targets,authorized_nodes)
    def same(a,b):
        if a.get('id') in existing_targets:
            if a.tag!=b.tag or a.get('id')!=b.get('id') or a.tail!=b.tail:raise ValueError('insertion guard: authorized target moved/replaced')
            if any(n.get('id') in old and n.get('id') not in authorized_ids for n in b.iter()):raise ValueError('insertion guard: protected ID borrowed into target')
            return
        if (a.tag,a.attrib,a.text,a.tail)!=(b.tag,b.attrib,b.text,b.tail):raise ValueError('insertion guard: protected node changed')
        children=list(a);position=0
        for child in b:
            if child.get('id') and child.get('id') not in old:
                if a.get('id') not in anchors:raise ValueError('insertion guard: insertion outside exact anchor')
                fresh(child);continue
            if position>=len(children):raise ValueError('insertion guard: unlabelled insertion')
            same(children[position],child);position+=1
        if position!=len(children):raise ValueError('insertion guard: protected child removed')
    same(before,after)
    # No protected old identity can be replaced or disappear behind an exception.
    for ident in set(old)-authorized_ids:
        if ident not in new:raise ValueError('insertion guard: protected identity removed')
    return {'inserted_root_ids':inserted,'protected_existing_ids':sorted(set(old)-authorized_ids),'insertion_anchor_ids':list(anchors),'separately_authorized_existing_targets':list(existing_targets),'dependency_proof':dependency}


@contextmanager
def transactions(native,programs,issues,images,receipt_path):
    """Wrap both trial output and checkpoint proof inside native rollback scope."""
    bindings={}
    for image in images:
        selected=[p for p in programs if p['image_id']==image]
        local=bind(selected,issues,images[image]['svg'])
        for _,entry in local.items():
            indices=[i for i,p in enumerate(programs) if p['id']==entry['program']['id']]
            if len(indices)!=1:raise ValueError('insertion guard: ambiguous program identity')
            bindings[indices[0]]=entry
    originals=(native.run_code,native.write_checkpoint)
    current={im:Path(row['svg']) for im,row in images.items()};receipts=[]
    receipt_path=Path(receipt_path);receipt_path.parent.mkdir(parents=True,exist_ok=True)
    if receipt_path.exists():raise ValueError('insertion guard: receipt already exists')
    # Durable manifest means no successful path can silently omit the guard.
    def record(row):
        receipts.append(row)
        with receipt_path.open('a') as stream:
            stream.write(json.dumps(row,sort_keys=True)+'\n');stream.flush();os.fsync(stream.fileno())
    record({'format':'insertion-common-guard-v1','event':'installed','bound_program_ids':[v['program']['id'] for v in bindings.values()]})
    def proof(index,before_text,after_text,stage):
        binding=bindings[index];p=binding['program']
        row={'event':'proof','category':'common_guard','program_id':p['id'],'stage':stage,'program_sha256':digest(json.dumps(p,sort_keys=True)),'source_code_sha256':digest(p['source_code']) if p['route']=='generated_python' else None,'before_sha256':digest(before_text),'output_sha256':digest(after_text)}
        try:
            rights(p,issues,parse(before_text))
            row.update(prove(before_text,after_text,binding['anchors'],binding['existing_targets']),status='passed')
        except Exception as exc:
            row.update(status='failed',error=str(exc));record(row);raise
        record(row);return row
    def run_code(code,input_svg,output_dir,**kwargs):
        matches=[i for i,p in enumerate(programs) if p.get('route')=='generated_python' and p.get('source_code')==code]
        if not any(i in bindings for i in matches):
            return originals[0](code,input_svg,output_dir,**kwargs)
        if len(matches)!=1:raise ValueError('insertion guard: ambiguous sandbox source')
        index=matches[0];p=programs[index]
        if Path(input_svg).resolve()!=current[p['image_id']].resolve():raise ValueError('insertion guard: sandbox input source mismatch')
        before_text=Path(input_svg).read_text()
        try:
            result=originals[0](code,input_svg,output_dir,**kwargs)
        except Exception as exc:
            if index in bindings:record({'event':'proof','category':'common_guard','program_id':p['id'],'stage':'sandbox-output','program_sha256':digest(json.dumps(bindings[index]['program'],sort_keys=True)),'source_code_sha256':digest(code),'before_sha256':digest(before_text),'output_sha256':None,'status':'failed','error':str(exc)})
            raise
        if index in bindings and result.get('status')!='executed':
            record({'event':'proof','category':'common_guard','program_id':p['id'],'stage':'sandbox-output','program_sha256':digest(json.dumps(bindings[index]['program'],sort_keys=True)),'source_code_sha256':digest(code),'before_sha256':digest(before_text),'output_sha256':None,'status':'failed','error':result.get('error','sandbox failed before output')})
        if index in bindings and result.get('status')=='executed':
            receipt=proof(index,before_text,Path(result['svg']).read_text(),'sandbox-output')
            result['insertion_common_guard']=receipt
        return result
    def checkpoint(root,folder,index):
        p=programs[index];im=p['image_id']
        if index in bindings:
            row=proof(index,current[im].read_text(),ET.tostring(root,encoding='unicode'),'before-checkpoint')
            if row['status']!='passed':raise ValueError('insertion guard: missing successful receipt')
        result=originals[1](root,folder,index)
        current[im]=Path(result[0]['svg'])
        return result
    class Checked:
        def verify(self,result):
            for rec in result['rcd']:
                if rec['program_id'] not in {v['program']['id'] for v in bindings.values()} or rec['status'] not in ('changed_unverified','executed_no_change'):continue
                found=[r for r in receipts if r.get('program_id')==rec['program_id'] and r.get('status')=='passed' and r.get('stage')=='before-checkpoint']
                if not found:raise ValueError('insertion guard: missing postguard receipt')
                rec['insertion_common_guard']=found[-1]
            if not receipt_path.is_file():raise ValueError('insertion guard: missing receipt file')
    native.run_code=run_code;native.write_checkpoint=checkpoint
    try:yield Checked()
    finally:native.run_code,native.write_checkpoint=originals
