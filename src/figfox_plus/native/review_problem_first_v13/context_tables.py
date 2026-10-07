"""Lossless default tables; reduced model views require explicit opt-in."""
from copy import deepcopy
import hashlib
import xml.etree.ElementTree as ET


def compact_traced_assets(svg):
    """Elide anonymous tracing internals in model context only, never in the SVG file."""
    root=ET.fromstring(svg)
    indexed={node:'@node:'+str(index) for index,node in enumerate(list(root.iter())[1:])}
    omitted=set()
    for node in list(root.iter()):
        if indexed.get(node) in omitted:continue
        generated=node.get('data-plus-generated-asset')=='true' or node.get('desc','').startswith('Created with imagetracer.js')
        children=list(node.iter())[1:]
        if not generated or any(child.get('id') for child in children):continue
        source=ET.tostring(node,encoding='unicode')
        if len(children)<100 and len(source)<20000:continue
        omitted.update(indexed[child] for child in children)
        node[:]=[]
        node.set('data-context-asset-sha256',hashlib.sha256(source.encode()).hexdigest())
        node.set('data-context-omitted-nodes',str(len(children)))
    return (ET.tostring(root,encoding='unicode') if omitted else svg),omitted


def model_line_facts(facts, max_pairs=None, *, omit_ids=()):
    """Keep all facts by default; callers may explicitly request a reduced view."""
    selected=deepcopy(facts)
    if omit_ids:
        omitted=set(omit_ids)
        original_count=len(selected.get('objects',[]))
        for key in ('objects','unsupported'):
            selected[key]=[r for r in selected.get(key,[]) if r.get('object_id') not in omitted]
        selected['relation_candidates']=[r for r in selected.get('relation_candidates',[]) if not omitted.intersection(r.get('object_ids',[]))]
        selected['opaque_asset_evidence']={
            'omitted_object_count':original_count-len(selected['objects']),
            'reason':'Anonymous vector tracing internals are opaque assets, not addressable arrow objects. Use the owning SVG group, measured bounds and rendered images.',
            'full_evidence':'current-line-facts.json and inputs/current SVG retain all geometry locally; generated code must read INPUT_SVG, never reconstruct omitted paths from this view.'}
    pairs=selected.get('relation_candidates',[])
    if max_pairs is not None and len(pairs)>max_pairs:
        by_object={}
        ordered=sorted(range(len(pairs)),key=lambda i:(min(pairs[i].get('endpoint_distances',{'distance':float('inf')}).values()),i))
        for index in ordered:
            for object_id in pairs[index].get('object_ids',[]):
                by_object.setdefault(object_id,[]).append(index)
        chosen=set()
        depth=0
        while len(chosen)<max_pairs:
            added=False
            for candidates in by_object.values():
                if depth<len(candidates):
                    chosen.add(candidates[depth]);added=True
                    if len(chosen)==max_pairs:break
            if not added:break
            depth+=1
        selected['relation_candidates']=[pairs[i] for i in sorted(chosen)]
        selected['relation_candidate_selection']={
            'total_count':len(pairs),'included_count':len(chosen),'omitted_count':len(pairs)-len(chosen),
            'policy':'nearest endpoints per object, round-robin; all object geometry retained',
            'full_evidence':'current-line-facts.json (local audit file, not included in model context)',
            'warning':'Omitted pairs are not evidence of absence; inspect original/current images and all object geometry.'}
    return compact_line_facts(selected)


def compact_line_facts(facts):
    out=deepcopy(facts)
    for key in ('objects','relation_candidates','unsupported'):
        records=out.get(key,[])
        tables=[];shapes={}
        for index,record in enumerate(records):
            columns=tuple(record)
            distances=record.get('endpoint_distances') if key=='relation_candidates' else None
            nested=tuple(distances) if isinstance(distances,dict) and set(distances)=={'start_start','start_end','end_start','end_end'} else ()
            shape=(columns,nested)
            if shape not in shapes:
                shapes[shape]=len(tables)
                table={'columns':['record_index',*columns],'rows':[]}
                if nested:table['nested_columns']={'endpoint_distances':list(nested)}
                tables.append(table)
            values=[list(value.values()) if name=='endpoint_distances' and nested else value for name,value in record.items()]
            tables[shapes[shape]]['rows'].append([index,*values])
        out[key]={'encoding':'column_named_tables','record_count':len(records),'tables':tables}
    out['table_encoding_instruction']='Read each row by its column names. For a field listed in nested_columns, read its value vector by those nested column names. record_index restores original order. All records and exact measured values are retained; tables are candidates, not confirmed visual defects.'
    return out


def expand_line_facts(facts):
    out=deepcopy(facts);out.pop('table_encoding_instruction',None)
    for key in ('objects','relation_candidates','unsupported'):
        value=out[key];records=[None]*value['record_count']
        for table in value['tables']:
            for row in table['rows']:
                record=dict(zip(table['columns'][1:],row[1:]))
                for field,columns in table.get('nested_columns',{}).items():
                    if not isinstance(record[field],list) or len(record[field])!=len(columns):raise ValueError('invalid nested table row')
                    record[field]=dict(zip(columns,record[field]))
                records[row[0]]=record
        out[key]=records
    return out
