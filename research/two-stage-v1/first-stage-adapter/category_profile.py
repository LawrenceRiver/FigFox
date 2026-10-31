"""Prospective lean6 + A/C/S4 help; never modifies native validation code."""
from copy import deepcopy
from pathlib import Path
from flow import MAIN_CATEGORIES, EXTRA_CATEGORIES, SEMANTIC_CATEGORIES, PROFILE_CATEGORIES, PROFILE_ID, digest, sha

# Explicit schema/guard sources only; no tasks, labels, tests, or historical outputs.
CONTRACT_SOURCES = (
    'native/review_problem_first_v13/lean_inspection.py',
    'native/review_problem_first_v13/methods.py',
    'native/review_problem_first_v13/execution_contract.py',
    'native/review_problem_first_v13/replay.py',
    'native/review_problem_first_v13/programs.py',
    'native/review_problem_first_v13/quality.py',
    'native/review_problem_first_v13/capacity_program_contract.py',
    'native/review_problem_first_v13/capacity_scope.py',
    'native/review_problem_first_v13/scene.py',
    'native/single_call/contract.py',
    'native/single_call/executor.py',
    'native/repair_toolbox.py',
    'native/sp_v2.py',
    'native/tp_v2.py',
)

def build_profile_pack(methods, lean, capabilities=None):
    pack=deepcopy(methods.build_method_pack(capabilities=capabilities))
    # Replace first-generation construction/manual text with shared review quality.
    # Otherwise native disabled packs retain first_native tool-declaration recipes.
    here=Path(__file__).resolve().parent
    pack['common_quality']=(here/'prompts/common.md').read_text()+'\n'+lean.PROMPT+'\n'+(here/'docs/category-profile.md').read_text()
    from figfox_plus.native.capability_prompts import COMMON_CONDITIONAL_POLICY,METHOD_APPLICABILITY
    pack['common_conditional_policy']=COMMON_CONDITIONAL_POLICY+'\n'+METHOD_APPLICABILITY
    if not pack["assignment"]["code_methods"]:
        pack.update(profile_id=PROFILE_ID, inspection_order=list(PROFILE_CATEGORIES), role_categories={"main":list(MAIN_CATEGORIES),"semantic":list(SEMANTIC_CATEGORIES)})
        pack.pop("version_hash",None);pack["version_hash"]=digest(pack)
        return pack
    original_hash=pack['version_hash'];cards={x['id']:x for x in pack['cards']}
    for category in ('C','D','S4'):
        cards[category]={'id':category,'name':category,'definition':methods._DETAILS[category]['observe'][0],**deepcopy(methods._DETAILS[category]),'source':'methods._DETAILS['+category+']'}
    # S2 in methods._DETAILS is the legacy planar definition, explicitly excluded.
    cards['S2']={'id':'S2','name':'Inconsistent Patches (lean)','definition':lean.PROMPT.split('\nS2 Inconsistent Patches.')[1].split('Perform one general inspection pass')[0].strip(),
                 'execute':[lean.REPAIR_PROMPT.split('For S2, Inconsistent Patches.')[1].split('When using sp_photo')[0].strip()],
                 'methods':['sp_photo'],'source':'lean_inspection.PROMPT and REPAIR_PROMPT; never methods._DETAILS[S2]'}
    for category in ('S1','D','S2'):
        cards[category]['lean_repair_contract']=lean.REPAIR_PROMPT.split('For '+category+',')[1].split('\nFor ')[0].split('\nWhen using sp_photo')[0].strip()
    cards['S4']['necessity_limit']='Only source-supported semantically meaningful count obligations; decorative marks and SVG path counts are insufficient.'
    for card in cards.values():
        card.pop('version_hash',None);card['version_hash']=digest(card)
    pack.update(format='harness-profile-method-pack-v2',profile_id=PROFILE_ID,native_default_version_hash=original_hash,
                native_default_inspection_order=pack['inspection_order'],inspection_order=list(PROFILE_CATEGORIES),
                repair_order={'policy':'Derive execution order from actual scoped dependencies; inspection order is not execution order. Native D-only/S2-only programs require empty dependencies.','allowed_categories':list(PROFILE_CATEGORIES)},
                role_categories={'main':list(MAIN_CATEGORIES),'semantic':list(SEMANTIC_CATEGORIES)},
                supplemental_extra_categories=list(EXTRA_CATEGORIES),
                supplemental_duty='Correspondence and completeness; use the category matching each observed phenomenon without reclassification. This is not a second full main-category sweep.',
                cards=[cards[x] for x in PROFILE_CATEGORIES],
                lean_inspection_prompt=lean.PROMPT,lean_repair_prompt=lean.REPAIR_PROMPT,
                profile_contract='Read docs/category-profile.md and docs/native-contract.md; native validation remains authoritative. No relabel after rejection; unsupported findings remain unresolved.')
    pack.pop('version_hash',None);pack['version_hash']=digest(pack)
    return pack


def build_native_contract(root, pack, capabilities=None):
    root=Path(root).resolve();source=root/'source'/'src'/'figfox_plus'
    enabled=pack['assignment']['code_methods']
    paths=[{'path':str(source/p),'sha256':sha(source/p),'readonly':True} for p in CONTRACT_SOURCES] if enabled else []
    return {'format':'harness-schema-contract-v2','profile_id':PROFILE_ID,'schema_only':True,
            'method_pack':str(root/'inputs'/'method-pack.json'),'method_pack_hash':pack['version_hash'],
            'profile':str(root/'docs'/'category-profile.md'),'full_contract':str(root/'docs'/'native-contract.md'),
            'native_sources':paths,'runtime_contract':pack['runtime_contract'],'operation_contract':pack['operation_contract'],
            'availability_manifest':pack['assignment'],
            **({'lean_repair_contract':pack['lean_repair_prompt']} if enabled else {}),
            'boundary':'Generic schema/guard source and placeholder protocol only; no case observations or coordinates. Read supplied schema sources only when enabled by assignment. Native acceptance is not rendered satisfaction.'}
