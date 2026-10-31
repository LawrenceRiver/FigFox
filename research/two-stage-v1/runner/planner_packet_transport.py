"""Lossless dictionary field templates for repetitive measured-geometry packets."""
from collections import Counter
import json,re

def decode(view):
    schemas=view['field_templates']
    def visit(value):
        if isinstance(value,dict):
            if set(value)=={'$pt'}:
                index,values=value['$pt'];keys=schemas[index]
                if len(keys)!=len(values):raise ValueError('template arity mismatch')
                return {key:visit(child) for key,child in zip(keys,values)}
            return {key:visit(child) for key,child in value.items()}
        return [visit(child) for child in value] if isinstance(value,list) else value
    return visit(view['data'])

def encode(document):
    counts=Counter()
    def count(value):
        if isinstance(value,dict):
            if '$pt' in value:raise ValueError('reserved field-template marker collision')
            counts[tuple(value)]+=1
            for child in value.values():count(child)
        elif isinstance(value,list):
            for child in value:count(child)
    count(document)
    templates=[keys for keys,n in counts.items() if n>=3 and len(keys)>=3 and sum(len(key)+3 for key in keys)>24]
    indices={keys:i for i,keys in enumerate(templates)}
    def visit(value):
        if isinstance(value,dict):
            keys=tuple(value)
            if keys in indices:return {'$pt':[indices[keys],[visit(child) for child in value.values()]]}
            return {key:visit(child) for key,child in value.items()}
        return [visit(child) for child in value] if isinstance(value,list) else value
    result={'format':'lossless-field-templates-v1','decode':'For any object whose sole key is $pt, interpret its value as [template_index, values]. Replace it by dict(zip(field_templates[template_index], values)), recursively decoding all values. Other dictionaries/lists/scalars are unchanged. Preserve all float digits and array ordering.','field_templates':[list(keys) for keys in templates],'data':visit(document)}
    if decode(result)!=document:raise ValueError('field template inverse equality failed')
    return result

def decode_lines(view):
    def visit(value):
        if isinstance(value,str):
            for marker,line in view['line_aliases'].items():value=value.replace(marker,line)
            return value
        if isinstance(value,dict):return {key:visit(child) for key,child in value.items()}
        return [visit(child) for child in value] if isinstance(value,list) else value
    return visit(view['data'])

def encode_lines(document):
    counts=Counter();strings=[]
    def count(value):
        if isinstance(value,str):
            strings.append(value);counts.update(line for line in value.splitlines(keepends=True) if len(line)>=64)
            # Repeated exact prose spans can occur inside differently wrapped native briefs.
            positions=[match.start() for match in re.finditer(r'\S+',value)]
            for width in (32,64):
                for index in range(max(0,len(positions)-width)):
                    span=value[positions[index]:positions[index+width]]
                    if len(span)>=128:counts[span]+=1
        elif isinstance(value,dict):
            for child in value.values():count(child)
        elif isinstance(value,list):
            for child in value:count(child)
    count(document)
    prefix='~PL'
    while any(prefix in value for value in strings):prefix+='X'
    mapping={};projected=list(strings)
    candidates=sorted((line for line,n in counts.items() if n>=2 and (n-1)*len(line)>n*12+30),key=lambda s:(-len(s),s))
    for line in candidates:
        occurrences=sum(value.count(line) for value in projected)
        if occurrences<2 or (occurrences-1)*len(line)<=occurrences*16+40:continue
        marker=prefix+str(len(mapping))+'~';mapping[marker]=line
        projected=[value.replace(line,marker) for value in projected]
    def visit(value):
        if isinstance(value,str):
            for marker,line in mapping.items():value=value.replace(line,marker)
            return value
        if isinstance(value,dict):return {key:visit(child) for key,child in value.items()}
        return [visit(child) for child in value] if isinstance(value,list) else value
    result={'format':'lossless-line-aliases-v1','decode':'In every data string recursively, replace each literal line_aliases marker by its full exact prose value (including any newline characters). No instruction or rule is removed. Native original files remain unchanged.','line_aliases':mapping,'data':visit(document)}
    if decode_lines(result)!=document:raise ValueError('line alias inverse equality failed')
    return result

def decode_shared_lines(view,source):
    import hashlib
    if hashlib.sha256(source.encode()).hexdigest()!=view['shared_source_sha256']:raise ValueError('shared instruction source changed')
    lines=source.splitlines(keepends=True);parts=[]
    for segment in view['segments']:
        if 'literal' in segment:parts.append(segment['literal'])
        else:
            start,end=segment['source_lines'];parts.append(''.join(lines[start:end]))
    result=''.join(parts)
    if hashlib.sha256(result.encode()).hexdigest()!=view['original_sha256']:raise ValueError('shared instruction inverse proof failed')
    return result

def encode_shared_lines(text,source):
    import difflib,hashlib
    a=source.splitlines(keepends=True);b=text.splitlines(keepends=True);segments=[];offset=0
    for block in difflib.SequenceMatcher(None,a,b,autojunk=False).get_matching_blocks():
        if block.b>offset:segments.append({'literal':''.join(b[offset:block.b])})
        if block.size:segments.append({'source_lines':[block.a,block.a+block.size]})
        offset=block.b+block.size
    view={'format':'lossless-shared-native-instructions-v1','decode':'After decoding the outer packet, split roles[0].instructions into lines retaining newline characters. For each segment in order, literal contributes its exact string; source_lines:[start,end] contributes the concatenation of that half-open line range from roles[0].instructions. Concatenate to reconstruct the COMPLETE semantic instructions with every rule unchanged.','shared_source':'roles[0].instructions','shared_source_sha256':hashlib.sha256(source.encode()).hexdigest(),'original_sha256':hashlib.sha256(text.encode()).hexdigest(),'segments':segments}
    if decode_shared_lines(view,source)!=text:raise ValueError('native instruction reconstruction mismatch')
    return view

def expand_refs(packet,table):
    def visit(value):
        if isinstance(value,dict):
            if set(value)=={'$r'}:
                index=value['$r']
                if type(index) is not int or not 0<=index<len(table):raise ValueError('invalid compact shared reference')
                return visit(table[index])
            return {key:visit(child) for key,child in value.items()}
        return [visit(child) for child in value] if isinstance(value,list) else value
    return visit(packet)

def compact_refs(packet,shared):
    key='$figfox_exact_json_ref';indices={ident:i for i,ident in enumerate(shared)}
    def visit(value):
        if isinstance(value,dict):
            if '$r' in value:raise ValueError('compact shared reference marker collision')
            if set(value)=={key}:return {'$r':indices[value[key]]}
            return {name:visit(child) for name,child in value.items()}
        return [visit(child) for child in value] if isinstance(value,list) else value
    result=visit(packet);table=[visit(value) for value in shared.values()]
    def expand_original(value):
        if isinstance(value,dict):
            if set(value)=={key}:return expand_original(shared[value[key]])
            return {name:expand_original(child) for name,child in value.items()}
        return [expand_original(child) for child in value] if isinstance(value,list) else value
    if expand_refs(result,table)!=expand_original(packet):raise ValueError('compact reference inverse equality failed')
    return result,table

def decode_wire(text):
    """Invert controller-owned transport views only; never execute model text."""
    import re
    notice=re.search(r'LOSSLESS ABSOLUTE-PATH ALIAS:.*?replace literal (.*?) with (.*?) before interpreting',text)
    if notice:text=text.replace(notice[1],notice[2])
    offset=text.find('{"format":')
    if offset<0:raise ValueError('no controller transport JSON envelope')
    value=json.loads(text[offset:])
    def map_keys(v,mapping):
        if isinstance(v,dict):return {mapping.get(k,k):map_keys(x,mapping) for k,x in v.items()}
        return [map_keys(x,mapping) for x in v] if isinstance(v,list) else v
    def paths(v,mapping):
        if isinstance(v,str):
            for marker,prefix in mapping.items():
                if v.startswith(marker):return prefix+v[len(marker):]
            return v
        if isinstance(v,dict):return {k:paths(x,mapping) for k,x in v.items()}
        return [paths(x,mapping) for x in v] if isinstance(v,list) else v
    if value.get('format')=='lossless-planner-packet-v2':
        packet=map_keys(value['packet'],value['key_aliases']);table=map_keys(value['shared_values'],value['key_aliases'])
        if isinstance(table,list):packet=expand_refs(packet,table)
        else:
            def expand(v):
                if isinstance(v,dict):
                    if set(v)=={'$figfox_exact_json_ref'}:return expand(table[v['$figfox_exact_json_ref']])
                    return {k:expand(x) for k,x in v.items()}
                return [expand(x) for x in v] if isinstance(v,list) else v
            packet=expand(packet)
        value=paths(packet,value.get('absolute_path_aliases',{}))
    elif value.get('format')=='lossless-path-prefix-packet-v1':value=paths(value['packet'],value['absolute_path_aliases'])
    if value.get('format')=='lossless-field-templates-v1':value=decode(value)
    if value.get('format')=='lossless-line-aliases-v1':value=decode_lines(value)
    return value
