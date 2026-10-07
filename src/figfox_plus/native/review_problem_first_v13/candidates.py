"""Retain ambiguous repairs as isolated, rendered alternatives without model calls."""
from pathlib import Path

from ...state import write_json
from .programs import execute_programs
from .replay import select_valid_programs


def source_candidates(programs, issues, images, folder, rejected, prior_executed=None):
    if not any(row.get('status') == 'deferred_source_geometry' for row in rejected):
        return []
    folder = Path(folder)
    summary = {'candidate_only': True, 'automatically_adopted': False,
               'visual_acceptance': 'pending', 'model_requests': 0,
               'base_revisions': {key: value['revision'] for key, value in images.items()},
               'images': {}, 'rcd': []}
    try:
        accepted, declined = select_valid_programs(programs, issues, images,
                                                  prior_executed=prior_executed, candidate_only=True)
        ambiguous = [program['id'] for program in accepted
                     if any(check.get('candidate_only') for check in program.get('source_geometry_checks', []))]
        if not ambiguous:
            return []
        summary.update(program_ids=ambiguous, rejected_programs=declined)
        execution = execute_programs(accepted, issues, images, folder / 'execution',
                                     prior_executed=prior_executed, candidate_only=True)
        summary['rcd'] = execution['rcd']
        changed_images = {row['image_id'] for row in execution['rcd']
                          if row['program_id'] in ambiguous and row['status'] == 'changed_unverified'}
        summary['images'] = {key: value for key, value in execution['images'].items() if key in changed_images}
        summary['status'] = 'available' if summary['images'] else 'not_materialized'
    except Exception as error:
        # A candidate cannot prevent unrelated canonical repairs or fallback output.
        summary.update(status='failed', error=type(error).__name__ + ': ' + str(error))
    write_json(folder / 'result.json', summary)
    return [summary]
