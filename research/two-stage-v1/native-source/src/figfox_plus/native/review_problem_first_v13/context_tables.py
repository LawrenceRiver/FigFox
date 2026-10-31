"""Lossless table encoding of repeated measured fields; never prune evidence."""
from copy import deepcopy
import json


def _pool_columns(table):
    """A per-column dictionary stores repeated values once, without rounding."""
    dictionaries={}
    for index,name in enumerate(table['columns']):
        values=[];lookup={};references=[]
        original=[row[index] for row in table['rows']]
        for value in original:
            # Keep JSON types and original dictionary order distinct.
            key=json.dumps(value,ensure_ascii=False,separators=(',',':'))
            if key not in lookup:
                lookup[key]=len(values);values.append(value)
            references.append(lookup[key])
        size=lambda value:len(json.dumps(value,ensure_ascii=False,separators=(',',':')))
        if size(values)+size(references)+len(name)+40 < size(original):
            dictionaries[name]=values
            for row,reference in zip(table['rows'],references):row[index]=reference
    if dictionaries:table['column_dictionaries']=dictionaries


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
        for table in tables:_pool_columns(table)
        out[key]={'encoding':'column_named_tables','record_count':len(records),'tables':tables}
    out['table_encoding_instruction']='Read each row by its column names. For a column in column_dictionaries, the row cell is a zero-based index into that column dictionary: resolve it first. For a field in nested_columns, then read its value vector by those nested column names. record_index restores original order. Every record and exact value is retained; candidates are not confirmed visual defects.'
    return out


def expand_line_facts(facts):
    out=deepcopy(facts);out.pop('table_encoding_instruction',None)
    for key in ('objects','relation_candidates','unsupported'):
        value=out[key];records=[None]*value['record_count']
        for table in value['tables']:
            for row in table['rows']:
                record=dict(zip(table['columns'][1:],row[1:]))
                for field,values in table.get('column_dictionaries',{}).items():
                    reference=record[field]
                    if type(reference) is not int or not 0<=reference<len(values):raise ValueError('invalid column dictionary reference')
                    record[field]=deepcopy(values[reference])
                for field,columns in table.get('nested_columns',{}).items():
                    if not isinstance(record[field],list) or len(record[field])!=len(columns):raise ValueError('invalid nested table row')
                    record[field]=dict(zip(columns,record[field]))
                records[row[0]]=record
        out[key]=records
    return out
