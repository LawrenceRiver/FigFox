"""Rename only provably unreferenced duplicated operation-result identifiers.

The executable reference grammar is {$result: {step: ID, path: [...]}} from
native.single_call.executor._resolve. `$ref` is not an executable alias. This
helper does not rewrite references, program IDs, SVG IDs, source code, or any
operation parameter. It never executes programs, reads files, or calls APIs.

Call on the COMPLETE decoded plan before selecting/rejecting any programs.
Passing a filtered subset cannot establish global absence of references.
The caller must still run the usual program/dependency/scope validators.
"""
from collections import defaultdict
from copy import deepcopy


def _scan_references(value, path, references, reserved, problems, depth=0):
    if depth > 128:
        raise ValueError('plan nesting exceeds normalization limit')
    if isinstance(value, str):
        reserved.add(value)
    elif isinstance(value, dict):
        reserved.update(k for k in value if isinstance(k, str))
        if '$ref' in value:
            problems.append({'code': 'unsupported_reference_syntax', 'path': path + ['$ref'],
                             'error': '$ref is not the executor result-reference grammar; no scope guessing'})
        if '$result' in value:
            spec = value['$result']
            valid = (isinstance(spec, dict) and isinstance(spec.get('step'), str) and bool(spec['step'])
                     and set(spec) <= {'step', 'path'} and isinstance(spec.get('path', []), list)
                     and all(isinstance(k, str) or type(k) is int for k in spec.get('path', [])))
            if not valid:
                problems.append({'code': 'malformed_result_reference', 'path': path + ['$result'],
                                 'error': 'cannot prove absence of references in malformed $result'})
            else:
                references[spec['step']].append(path + ['$result', 'step'])
        for key, child in value.items():
            _scan_references(child, path + [key], references, reserved, problems, depth + 1)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_references(child, path + [index], references, reserved, problems, depth + 1)


def _operations(operations, path, depth=0):
    if depth > 128: raise ValueError('operation nesting exceeds normalization limit')
    if not isinstance(operations, list): raise ValueError('operations must be an array')
    for index, operation in enumerate(operations):
        where = path + [index]
        if not isinstance(operation, dict): raise ValueError('operation must be an object')
        ident = operation.get('id')
        if ident is not None and (not isinstance(ident, str) or not ident):
            raise ValueError('operation result id must be a nonempty string when supplied')
        yield operation, where
        if operation.get('method') == 'bp_program':
            args = operation.get('args')
            if not isinstance(args, dict): raise ValueError('bp_program args must be an object')
            yield from _operations(args.get('operations'), where + ['args', 'operations'], depth + 1)


def normalize_unreferenced_result_ids(plan):
    """Return (deepcopied_plan, audit), never modifying the supplied plan.

    All occurrences of an eligible duplicate are renamed deterministically.
    A duplicate colliding with ANY program ID, or referenced anywhere in the
    complete plan, remains unchanged and is reported as a rejection. Other
    independent eligible duplicate groups may still be normalized.

    Unknown/malformed reference syntax or unreadable operation structure blocks
    ALL renames, because global unreferencedness cannot safely be established.
    Execution callers must handle audit.rejections explicitly; status=unchanged
    or normalized does not establish overall executable-plan validity.
    """
    normalized = deepcopy(plan)
    audit = {'status': 'unchanged', 'changes': [], 'rejections': [],
             'reference_grammar': '$result.step (optional path)',
             'scope': 'complete supplied plan; module_program args.operations and nested bp_program only',
             'requires_contract_validation': True}
    references, occurrences = defaultdict(list), defaultdict(list)
    reserved, program_ids = set(), set()
    try:
        if not isinstance(normalized, dict) or not isinstance(normalized.get('programs'), list):
            raise ValueError('complete plan with programs array required')
        _scan_references(normalized, [], references, reserved, audit['rejections'])
        for program_index, program in enumerate(normalized['programs']):
            if not isinstance(program, dict) or not isinstance(program.get('id'), str) or not program['id']:
                raise ValueError('program must have a nonempty string identity')
            program_ids.add(program['id'])
            route = program.get('route')
            if route == 'generated_python': continue
            if route != 'module_program': raise ValueError('unsupported program route; result namespace unknown')
            args = program.get('args')
            if not isinstance(args, dict): raise ValueError('module_program args must be an object')
            for ordinal, (operation, path) in enumerate(_operations(
                    args.get('operations'), ['programs', program_index, 'args', 'operations'])):
                ident = operation.get('id')
                if ident is None: continue
                occurrences[ident].append({'operation': operation, 'program_index': program_index,
                                           'program_id': program['id'], 'ordinal': ordinal, 'path': path + ['id']})
                reserved.add(ident)
        reserved.update(program_ids)
    except (ValueError, TypeError, RecursionError) as exc:
        audit['rejections'].append({'code': 'normalization_unavailable', 'error': str(exc)})
    if audit['rejections']:
        audit['status'] = 'blocked'
        return normalized, audit

    for ident, group in occurrences.items():
        if len(group) < 2: continue
        locations = [{k: entry[k] for k in ('program_index', 'program_id', 'path')} for entry in group]
        if ident in program_ids or ident in references:
            audit['rejections'].append({
                'code': 'program_id_collision' if ident in program_ids else 'referenced_duplicate',
                'id': ident, 'occurrences': deepcopy(locations),
                'reference_paths': deepcopy(references.get(ident, [])),
                'error': 'duplicate result identifiers preserved; reference/program scope must not be guessed',
            })
            continue
        for entry in group:
            base = f"__unreferenced_result_p{entry['program_index']:04d}_n{entry['ordinal']:04d}"
            candidate, suffix = base, 2
            while candidate in reserved:
                candidate = f'{base}_{suffix}'
                suffix += 1
            reserved.add(candidate)
            entry['operation']['id'] = candidate
            audit['changes'].append({
                'program_index': entry['program_index'], 'program_id': entry['program_id'],
                'path': entry['path'][:], 'before': ident, 'after': candidate,
                'reason': 'duplicated operation result ID with no references anywhere in complete plan',
            })
    audit['status'] = ('partially_normalized_with_rejections' if audit['changes'] else 'blocked') if audit['rejections'] else (
        'normalized' if audit['changes'] else 'unchanged')
    return normalized, audit
