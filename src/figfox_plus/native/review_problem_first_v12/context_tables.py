"""Lossless table encoding of repeated measured fields; never prune evidence."""
from copy import deepcopy


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
