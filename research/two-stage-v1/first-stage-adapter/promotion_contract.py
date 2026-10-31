"""Versioned active-uncertainty confirmation patch; immutable metadata is host-owned."""
from copy import deepcopy

SCHEMA_VERSION = 'uncertainty-promotion-patch-v1'
REQUIRED_KEYS = frozenset(('schema_version', 'id', 'decision', 'target_ids', 'neighbor_ids', 'evidence'))
OPTIONAL_KEYS = frozenset(('container_id',))
MUTABLE_ISSUE_KEYS = frozenset(('decision', 'target_ids', 'neighbor_ids', 'container_id', 'current_evidence'))


def promote_uncertainty(canonical, review):
    """Copy an exact current uncertainty and apply only explicitly supplied fields.

    Flow owns current-queue identity/uniqueness and candidate/revision checks;
    validate_issues must validate this result against the actual candidate SVG.
    This function never fills bindings/evidence from a previous report.
    """
    if not isinstance(review, dict) or not REQUIRED_KEYS <= review.keys() or review.keys() - (REQUIRED_KEYS | OPTIONAL_KEYS):
        raise ValueError('promotion patch requires exact versioned fields; current_issue and unknown keys are rejected')
    if review['schema_version'] != SCHEMA_VERSION:
        raise ValueError('promotion patch schema_version must be '+SCHEMA_VERSION)
    ident = review['id']
    if not isinstance(ident, str) or not ident.strip() or review['decision'] != 'confirmed':
        raise ValueError('promotion patch requires exact ID and confirmed decision')
    if not isinstance(canonical, dict) or canonical.get('id') != ident or canonical.get('decision') != 'uncertain':
        raise ValueError('promotion patch requires same current active uncertainty')
    for key in ('target_ids', 'neighbor_ids'):
        values = review[key]
        if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values) or len(values) != len(set(values)):
            raise ValueError('promotion patch requires unique string '+key)
    if 'container_id' in review and (not isinstance(review['container_id'], str) or not review['container_id'].strip()):
        raise ValueError('promotion patch requires an explicit string container_id')
    if not isinstance(review['evidence'], str) or not review['evidence'].strip():
        raise ValueError('promotion patch requires nonempty post-render evidence')
    current = deepcopy(canonical)
    current['decision'] = 'confirmed'
    current['target_ids'] = deepcopy(review['target_ids'])
    current['neighbor_ids'] = deepcopy(review['neighbor_ids'])
    current.pop('container_id', None)
    if 'container_id' in review:
        current['container_id'] = review['container_id']
    current['current_evidence'] = review['evidence']
    if {k: v for k, v in current.items() if k not in MUTABLE_ISSUE_KEYS} != {k: v for k, v in canonical.items() if k not in MUTABLE_ISSUE_KEYS}:
        raise ValueError('uncertainty promotion must preserve finding identity/history')
    return current
