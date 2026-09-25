"""Deterministic three-pass coverage over the upstream region identities."""
CATEGORIES = ('A','B','C','D','E','F','S1','S2','S3','S4')


def make_schedule(inputs):
    schedule = []
    for pass_number in (1,2,3):
        for image_id, image in inputs['images'].items():
            if pass_number == 1:
                regions = [('full', image['original_png'],image['current_png'])]
            else:
                regions = [(p['pair_id'],p['original_asset'],p['current_asset']) for p in image['crop_pairs']]
            for category in CATEGORIES:
                for region_id, original,current in regions:
                    schedule.append({'image_id':image_id,'pass':pass_number,'category':category,'region_id':region_id,'original_asset_id':original['asset_id'],'current_asset_id':current['asset_id'],'evidence_assets':[original['asset_id'],current['asset_id']],'current_revision':image['current_revision']})
    return schedule
