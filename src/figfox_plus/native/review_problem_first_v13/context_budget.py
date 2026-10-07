"""Preserve evidence; estimated token pressure is advisory, not an API limit."""
from copy import deepcopy
import json
from .context_encoding import compact_content, json_text as _json

CONTEXT_TOKENS = 1_048_576
BODY_BYTES = 48 * 1024 * 1024
IMAGE_TOKENS = 1024
SAFETY_TOKENS = 32_768


class ContextCapacityError(ValueError):
    pass


def _estimate(body):
    # A UTF-8 byte per text token is deliberately pessimistic. Base64 images
    # are visual inputs, not tokenized text; reserve the documented image maximum.
    view = deepcopy(body)
    images = 0
    text_bytes = 0
    for message in view.get('messages', []):
        content = message.get('content')
        if isinstance(content, str):
            text_bytes += len(content.encode('utf-8'))
            message['content'] = '[text counted separately]'
        elif isinstance(content, list):
            for part in content:
                if part.get('type') in ('image_url', 'file'):
                    images += 1
                    if part['type'] == 'image_url':
                        part['image_url'] = {'url': '[visual input]'}
                    elif 'file_data' in part:
                        part['file_data'] = '[visual input]'
                elif part.get('type') == 'text':
                    text_bytes += len(part.get('text', '').encode('utf-8'))
                    part['text'] = '[text counted separately]'
        if isinstance(message.get('reasoning_content'), str):
            text_bytes += len(message['reasoning_content'].encode('utf-8'))
            message['reasoning_content'] = '[reasoning counted separately]'
        for call in message.get('tool_calls') or []:
            function = call.get('function', {})
            if isinstance(function.get('arguments'), str):
                text_bytes += len(function['arguments'].encode('utf-8'))
                function['arguments'] = '[arguments counted separately]'
    # Count decoded model text once, not the extra escaping in the wire JSON.
    # Include schema/metadata and a conservative per-message framing allowance.
    text_bytes += len(_json(view).encode('utf-8')) + 1024 * len(view.get('messages', []))
    return {'text_token_upper_bound': text_bytes,
            'image_count': images, 'image_token_reserve': images * IMAGE_TOKENS,
            'input_token_upper_bound': text_bytes + images * IMAGE_TOKENS}


def budget_request(body, *, context_tokens=CONTEXT_TOKENS, body_bytes=BODY_BYTES, input_token_limit=None):
    """Compact evidence losslessly under pressure; retain every field and value.

    A byte upper bound cannot prove that tokenized input exceeds capacity. The
    provider decides actual context admission. Explicit monetary limits and
    documented request-body/image-count limits remain enforced locally.
    """
    prepared = deepcopy(body)
    before = _estimate(prepared)
    reductions = []
    pressure = (before['input_token_upper_bound'] + prepared['max_tokens'] + SAFETY_TOKENS > context_tokens
                or (input_token_limit is not None and before['input_token_upper_bound'] > input_token_limit))
    if pressure:
        # Keep ordinary inputs in their original format. Structured encoding is
        # reserved for literal input larger than the window's byte estimate, or
        # an explicitly configured money limit; it never reduces output quota.
        structural = (before['input_token_upper_bound'] > context_tokens
                      or (input_token_limit is not None and before['input_token_upper_bound'] > input_token_limit))
        for message in prepared.get('messages', []):
            # Assistant reasoning, tool IDs and message boundaries stay untouched.
            if message.get('role') != 'user' or not isinstance(message.get('content'), list):
                continue
            try:
                content, edits = compact_content(message['content'], structural=structural)
            except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError, OverflowError) as error:
                # A failed optimization cannot discard evidence or gate the
                # existing workflow. Preserve this message and record why.
                reductions.append({'field': 'lossless_encoding_skipped', 'reason': type(error).__name__,
                                   'original_message_preserved': True})
            else:
                message['content'] = content
                reductions.extend(edits)
    after = _estimate(prepared)
    audit = {'before': before, 'after': after, 'reductions': reductions,
             'context_tokens': context_tokens, 'output_token_reserve': prepared['max_tokens'],
             'input_cost_token_limit': input_token_limit,
             'safety_token_reserve': SAFETY_TOKENS,
             'request_body_bytes': len(json.dumps(prepared, ensure_ascii=False, sort_keys=True).encode('utf-8')),
             'request_body_limit_bytes': body_bytes, 'model_request_sent': False,
             'estimation': 'UTF-8 text byte upper bound plus 1024 tokens per image; not provider token usage'}
    violations = []
    warnings = []
    if after['input_token_upper_bound'] + prepared['max_tokens'] + SAFETY_TOKENS > context_tokens:
        warnings.append('estimated context pressure; actual provider token count unknown')
    if input_token_limit is not None and after['input_token_upper_bound'] > input_token_limit:
        violations.append('input cost budget')
    if audit['request_body_bytes'] > body_bytes:
        violations.append('request body size')
    if after['image_count'] > 600:
        violations.append('image count')
    audit['status'] = 'blocked_before_request' if violations else 'ready'
    audit['violations'] = violations
    audit['warnings'] = warnings
    audit['semantic_fields_removed'] = []
    return prepared, audit
