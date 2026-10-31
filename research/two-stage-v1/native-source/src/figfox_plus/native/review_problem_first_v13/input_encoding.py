"""Lossless request-only schedule encoding; discovery records stay independent."""
from copy import deepcopy
from .inspection_contract import CATEGORIES, inspection_regions


def compact_category_itinerary(schedule):
    regions=inspection_regions(schedule)
    ids=[r['region'] for r in regions]
    return {
        'region_catalog':regions,
        'category_itinerary':[{'category':category,'region_ids':ids[:]} for category in CATEGORIES],
        'region_catalog_instruction':'Resolve each integer in region_ids by the region field of region_catalog, in the listed order; these integers are not the string crop region_id. Complete every listed region separately for every category. Passes 2 and 3 remain independent inspections even when their crop assets are identical. No observation is shared across categories or passes.',
    }


def expand_category_itinerary(encoded):
    """Recover the former complete itinerary without manufacturing any evidence."""
    catalog=encoded['region_catalog'];itinerary=encoded['category_itinerary']
    by_id={}
    for region in catalog:
        rid=region['region']
        if type(rid) is not int or rid in by_id:raise ValueError('invalid or duplicate region identity')
        by_id[rid]=region
    expected=list(by_id)
    if [entry['category'] for entry in itinerary]!=list(CATEGORIES):raise ValueError('category order incomplete')
    expanded=[]
    for entry in itinerary:
        ids=entry['region_ids']
        if any(type(rid) is not int for rid in ids) or ids!=expected:raise ValueError('region coverage or order incomplete')
        expanded.append({'category':entry['category'],'regions':[deepcopy(by_id[rid]) for rid in ids]})
    return expanded
