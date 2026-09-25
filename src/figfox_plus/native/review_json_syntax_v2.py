"""Versioned complete-JSON parser; never fills missing model fields.

Adds only a complete-object premature closing brace recovery. All suffix text
must participate in a single valid object after deleting exactly that brace.
No strings, keys, values or executable code are rewritten.
"""
import hashlib
import json
from .review_json_syntax import parse_complete_json as _base, _reject_constant, _outside_string


def _unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('ambiguous duplicate JSON key')
        result[key]=value
    return result


def _bridge(source):
    decoder=json.JSONDecoder(parse_constant=_reject_constant,object_pairs_hook=_unique)
    start=len(source)-len(source.lstrip())
    prefix,end=decoder.raw_decode(source,start)
    suffix=source[end:].lstrip()
    if (not isinstance(prefix,dict) or not suffix.startswith(',')
            or not suffix[1:].lstrip().startswith('"')
            or source[end-1]!='}' or not _outside_string(source,end-1)):
        raise ValueError('not a single premature root object closer')
    candidate=source[:end-1]+source[end:]
    value=json.loads(candidate,parse_constant=_reject_constant,object_pairs_hook=_unique)
    if not isinstance(value,dict):raise ValueError('complete object required')
    return value,[{'kind':'premature_root_object_closer','offset':end-1,
                   'deleted':'}','before':'}','after':'',
                   'source_sha256':hashlib.sha256(source.encode()).hexdigest()}]


def parse_complete_json(source):
    try:return _base(source)
    except json.JSONDecodeError as original:
        if original.msg!='Extra data':raise
        try:outer=json.loads(source,parse_constant=_reject_constant,object_pairs_hook=_unique)
        except json.JSONDecodeError:
            return _bridge(source)
        if isinstance(outer,dict) and set(outer)=={'arguments'} and isinstance(outer['arguments'],str):
            inner=outer['arguments'];value,edits=_bridge(inner)
            return value,[{'kind':'single_arguments_string_envelope',
                          'source_sha256':hashlib.sha256(source.encode()).hexdigest(),
                          'inner_sha256':hashlib.sha256(inner.encode()).hexdigest()},*edits]
        raise original
