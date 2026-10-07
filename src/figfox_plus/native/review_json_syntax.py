"""Parse complete JSON with narrowly audited syntax/envelope normalization.

No schema validation, field completion, fence stripping, expression evaluation,
trailing-text removal or truncated-response recovery occurs here. Callers must
validate the returned value against their own output contract.
"""
import hashlib
import json


MAX_DELIMITER_CORRECTIONS = 32


def _reject_constant(value):
    raise ValueError('non-JSON numeric constant: ' + value)


def _outside_string(source, offset):
    """Track JSON quoting/escapes up to the parser's exact error position."""
    inside = False
    escaped = False
    for character in source[:offset]:
        if inside:
            if escaped:
                escaped = False
            elif character == '\\':
                escaped = True
            elif character == '"':
                inside = False
        elif character == '"':
            inside = True
    return not inside


def _unwrap_arguments(value, edits, digest):
    """Unwrap exactly one explicit string envelope, without repairing its body."""
    if (isinstance(value, dict) and set(value) == {'arguments'}
            and isinstance(value['arguments'], str)):
        inner = value['arguments']
        decoded = json.loads(inner, parse_constant=_reject_constant)
        if not isinstance(decoded, dict):
            raise ValueError('arguments envelope body must be a complete JSON object')
        edits.append({
            'kind': 'single_arguments_string_envelope',
            'source_sha256': digest,
            'inner_sha256': hashlib.sha256(inner.encode('utf-8')).hexdigest(),
        })
        return decoded, edits
    return value, edits


def _open_container(source, offset):
    """Return the innermost unmatched { or [ before offset, outside strings."""
    stack = []
    inside = False
    escaped = False
    for character in source[:offset]:
        if inside:
            if escaped:
                escaped = False
            elif character == '\\':
                escaped = True
            elif character == '"':
                inside = False
        elif character == '"':
            inside = True
        elif character in '{[':
            stack.append(character)
        elif character == '}' and stack and stack[-1] == '{':
            stack.pop()
        elif character == ']' and stack and stack[-1] == '[':
            stack.pop()
    return stack[-1] if stack else ''


def _repair(source, digest, *, substitute_object_bracket):
    current = source
    edits = []
    permitted = {
        "Expecting ',' delimiter": ('，', ','),
        "Expecting ':' delimiter": ('：', ':'),
    }
    while True:
        try:
            value = json.loads(current, parse_constant=_reject_constant)
        except json.JSONDecodeError as error:
            rejected = current[error.pos:error.pos + 1]
            removed = sum(1 for edit in edits if edit['kind'] == 'parser_rejected_surplus_closer')
            outside = bool(rejected) and _outside_string(current, error.pos)
            if (substitute_object_bracket and error.msg == "Expecting ',' delimiter"
                    and rejected == ']' and outside
                    and _open_container(current, error.pos) == '{'
                    and len(edits) < MAX_DELIMITER_CORRECTIONS):
                edits.append({
                    'kind': 'parser_rejected_object_closer',
                    'offset': error.pos + removed,
                    'before': ']',
                    'after': '}',
                    'source_sha256': digest,
                    'parser_error': error.msg,
                })
                current = current[:error.pos] + '}' + current[error.pos + 1:]
                continue
            if (error.msg == "Expecting ',' delimiter" and rejected in ('}', ']')
                    and outside and len(edits) < MAX_DELIMITER_CORRECTIONS):
                # Earlier deletions sit before this error, so shift back to the raw source.
                edits.append({
                    'kind': 'parser_rejected_surplus_closer',
                    'offset': error.pos + removed,
                    'deleted': rejected,
                    'before': rejected,
                    'after': '',
                    'source_sha256': digest,
                    'parser_error': error.msg,
                })
                current = current[:error.pos] + current[error.pos + 1:]
                continue
            delimiters = permitted.get(error.msg)
            if (delimiters is None or len(edits) >= MAX_DELIMITER_CORRECTIONS
                    or current[error.pos:error.pos + 1] != delimiters[0]
                    or not outside):
                raise
            before, after = delimiters
            edits.append({
                'kind': 'parser_identified_fullwidth_delimiter',
                'offset': error.pos,
                'before': before,
                'after': after,
                'source_sha256': digest,
                'parser_error': error.msg,
            })
            current = current[:error.pos] + after + current[error.pos + 1:]
        else:
            return _unwrap_arguments(value, edits, digest)


def _decode_string_controls(source, digest):
    # strict=False only permits literal controls inside JSON strings. It still
    # requires one complete value and rejects malformed escapes or trailing text.
    value = json.loads(source, strict=False, parse_constant=_reject_constant)
    edits = []
    inside = escaped = False
    for offset, character in enumerate(source):
        if inside:
            if escaped:
                escaped = False
            elif character == '\\':
                escaped = True
            elif character == '"':
                inside = False
            elif ord(character) < 32:
                edits.append({'kind': 'unescaped_string_control', 'offset': offset,
                              'before': character, 'after': json.dumps(character)[1:-1],
                              'source_sha256': digest, 'decoded_string_preserved': True})
        elif character == '"':
            inside = True
    if not edits or len(edits) > MAX_DELIMITER_CORRECTIONS:
        raise ValueError('JSON string control correction limit exceeded')
    return _unwrap_arguments(value, edits, digest)


def parse_complete_json(source):
    """Return (decoded JSON value, edits) or reject the entire response.

    Delimiter edits substitute one same-length character at JSONDecodeError.pos,
    only when the parser asks for exactly that comma/colon outside a string.
    Positions are Python Unicode character offsets into the original source;
    its SHA-256 hashes the original UTF-8 bytes. Maximum: 32 edits.
    A ] closing an object is rewritten to } when that path yields one complete
    JSON value. Otherwise a surplus } or ] at the parser's comma error may be
    deleted. Truncation is not filled in. A sole-key arguments string is
    unwrapped once; its body must already be a complete JSON object, without
    any syntax repair.
    A complete value containing unescaped string control characters can also
    be decoded without changing any string value; each original offset is logged.
    This fallback does not combine with structural delimiter repairs.
    """
    if not isinstance(source, str):
        raise ValueError('JSON source must be a string')
    digest = hashlib.sha256(source.encode('utf-8')).hexdigest()
    try:
        return _repair(source, digest, substitute_object_bracket=True)
    except json.JSONDecodeError:
        try:
            return _repair(source, digest, substitute_object_bracket=False)
        except json.JSONDecodeError:
            return _decode_string_controls(source, digest)
