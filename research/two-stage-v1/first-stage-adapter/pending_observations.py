"""Quarantine rejected-candidate findings; current evidence alone grants authority.

No I/O, geometry inference, native execution, taxonomy migration or repair credit.
The caller supplies the existing issue validator bound to the actual candidate SVG.
"""
from copy import deepcopy

IDENTITY_FIELDS = ('id', 'image_id', 'category', 'description', 'original_evidence')
REVIEW_DECISIONS = ('confirmed_current', 'uncertain_current', 'not_present_current', 'duplicate_of', 'defer')


def _by_id(rows, label):
    if not isinstance(rows, list):
        raise ValueError(label + ' must be array')
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(label + ' row must be object')
        ident = row.get('id')
        if not isinstance(ident, str) or not ident.strip() or ident in result:
            raise ValueError(label + ' missing or duplicate ID')
        result[ident] = row
    return result


def capture_pending(existing, findings, *, raw_sha256, observed_revision,
                    retained_revision, before_evidence_hashes,
                    observed_evidence_hashes, round_number, report_path):
    """Copy immutable observations, never translating rejected bindings to active."""
    prior = _by_id(existing, 'pending observations')
    fresh = _by_id(findings, 'new observations')
    if set(prior) & set(fresh):
        raise ValueError('pending observation ID collision')
    result = deepcopy(existing)
    for finding in findings:
        result.append({
            'id': finding['id'], 'original_finding': deepcopy(finding),
            'original_decision': finding['decision'],
            'observed_revision': observed_revision,
            'retained_revision_at_capture': retained_revision,
            'raw_sha256': raw_sha256, 'report_path': report_path,
            'before_evidence_hashes': deepcopy(before_evidence_hashes),
            'observed_evidence_hashes': deepcopy(observed_evidence_hashes),
            'observed_round': round_number, 'status': 'pending',
            'current_edit_authority': False,
        })
    return result


def triage_pending(pending, reviews, *, active_issues, known_svg_ids,
                   validate_current_issue):
    """Validate candidate-specific reviews; return copied queues and audit receipts.

    Caller must discard this result on rollback. Only surviving current active
    issues (after the normal verifier partition/bindings) may be duplicate links.
    """
    observations = _by_id(pending, 'pending observations')
    review_map = _by_id(reviews, 'pending observation reviews')
    active = _by_id(active_issues, 'current active issues')
    if set(observations) & set(active):
        raise ValueError('pending observation collides with current active issue')
    if set(review_map) - set(observations):
        raise ValueError('unknown pending observation review ID')
    result = {'pending': [], 'required': [], 'uncertain': [], 'receipts': []}

    def validate_current(current):
        # The native-shaped validator remains authoritative, including all
        # required fields, taxonomy, and real missing-content container scope.
        validate_current_issue([current])
        refs = current['target_ids'] + current['neighbor_ids']
        if current.get('container_id') is not None:
            refs += [current['container_id']]
        if any(ident not in known_svg_ids for ident in refs):
            raise ValueError('unknown current SVG binding')

    for observation in pending:
        review = review_map.get(observation['id'])
        if review is None:
            result['pending'].append(deepcopy(observation))
            continue
        decision = review.get('decision')
        if decision not in REVIEW_DECISIONS:
            raise ValueError('invalid pending observation review decision')
        if not isinstance(review.get('evidence'), str) or not review['evidence'].strip():
            raise ValueError('pending observation review requires source/current evidence')
        allowed = {'id', 'decision', 'evidence'}
        if decision in ('confirmed_current', 'uncertain_current'):
            allowed.add('current_issue')
        elif decision == 'duplicate_of':
            allowed.add('duplicate_of_id')
        elif decision == 'not_present_current':
            allowed.add('reason')
        if set(review) != allowed:
            raise ValueError('missing or incompatible pending observation review fields')
        original = observation['original_finding']
        if decision in ('confirmed_current', 'uncertain_current'):
            current = review['current_issue']
            expected = 'confirmed' if decision == 'confirmed_current' else 'uncertain'
            if not isinstance(current, dict) or any(current.get(k) != original.get(k) for k in IDENTITY_FIELDS):
                raise ValueError('pending promotion must preserve identity/category/source evidence')
            if current.get('decision') != expected:
                raise ValueError('pending promotion current issue decision mismatch')
            # Preserve source provenance keys when present; candidate-only
            # metadata need not be copied into the canonical current issue.
            for key in ('source_issue_id', 'source_role'):
                if key in original and current.get(key) != original[key]:
                    raise ValueError('pending promotion must preserve source history')
            validate_current(current)
            result['required' if expected == 'confirmed' else 'uncertain'].append(deepcopy(current))
        elif decision == 'duplicate_of':
            target = review['duplicate_of_id']
            if not isinstance(target, str) or target not in active:
                raise ValueError('pending duplicate must link a current active issue')
            current = active[target]
            if any(current.get(k) != original.get(k) for k in ('image_id', 'category')):
                raise ValueError('pending duplicate has incompatible image/category')
            validate_current(current)
        elif decision == 'not_present_current':
            if not isinstance(review['reason'], str) or not review['reason'].strip():
                raise ValueError('pending dismissal requires source/current reason')
        elif decision == 'defer':
            result['pending'].append(deepcopy(observation))
            continue
        result['receipts'].append({**deepcopy(review), 'observation': deepcopy(observation), 'repair_credit': False})
    return result
