"""Explicit disabled-feature transport projection; never changes quality fields."""
from copy import deepcopy

def normalize(report, enabled):
    result = deepcopy(report)
    audit = []
    if enabled:
        return result, audit
    for key in ('connector_paint_ack', 'connector_visual_concerns', 'connector_concern_reviews'):
        if key not in result:
            continue
        value = result[key]
        unavailable_note=key=='connector_paint_ack' and isinstance(value,dict) and set(value)=={'status','reason'} and value['status']=='not_supplied' and isinstance(value['reason'],str)
        if value is not None and not unavailable_note and not (key != 'connector_paint_ack' and value == []):
            raise ValueError('nonempty disabled connector metadata requires diagnosis: ' + key)
        audit.append({'field': key, 'original_value': value, 'reason': 'disabled feature; empty unrequested metadata only'})
        del result[key]
    return result, audit
