"""Lossless table encoding of repeated measured fields; never prune evidence."""
from copy import deepcopy


def compact_line_facts(facts):
    out=deepcopy(facts)
    for key in ('objects','relation_candidates','unsupported'):
        records=out.get(key,[])
        tables=[];shapes={}
        for index,record in enumerate(records):
            columns=tuple(record)
            if columns not in shapes:
                shapes[columns]=len(tables)
                tables.append({'columns':['record_index',*columns],'rows':[]})
            tables[shapes[columns]]['rows'].append([index,*record.values()])
        out[key]={'encoding':'column_named_tables','record_count':len(records),'tables':tables}
    out['table_encoding_instruction']='Read each row by its column names. record_index restores original order. All records and exact measured values are retained; tables are candidates, not confirmed visual defects.'
    return out


def expand_line_facts(facts):
    out=deepcopy(facts);out.pop('table_encoding_instruction',None)
    for key in ('objects','relation_candidates','unsupported'):
        value=out[key];records=[None]*value['record_count']
        for table in value['tables']:
            for row in table['rows']:
                records[row[0]]=dict(zip(table['columns'][1:],row[1:]))
        out[key]=records
    return out
