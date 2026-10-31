"""Structural-only repair protocol normalization; never author a visual fix.

This is not an admission or execution bypass. The caller must retain the raw
program and pass the result through the original shape, selector and transaction
validators, including exact revision and planned-scope checks before selection.
"""
from copy import deepcopy
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from .programs import _compile_typed_scope


class ProgramContractError(ValueError):
    def __init__(self, message, program, log):
        super().__init__(message)
        self.raw_program = deepcopy(program)
        self.normalization_log = deepcopy(log)


def _literal(value):
    if isinstance(value,dict): return all(not str(k).startswith('$') and _literal(v) for k,v in value.items())
    if isinstance(value,list): return all(_literal(v) for v in value)
    return value is None or isinstance(value,(str,bool,int,float))


def _operation(value):
    return (isinstance(value,dict) and isinstance(value.get('method'),str)
            and isinstance(value.get('target_ids'),list)
            and all(isinstance(i,str) and i for i in value['target_ids'])
            and isinstance(value.get('args'),dict) and _literal(value))


def _operations(ops):
    for operation in ops:
        yield operation
        if operation.get('method')=='bp_program':
            yield from _operations(operation.get('args',{}).get('operations',[]))


def _rewrite_fragment(fragment, mapping):
    """Change only explicit identity/reference attribute bytes, preserving markup."""
    if not mapping: return fragment
    if re.search(r'<(?:\w+:)?(?:style|script)\b',fragment):
        raise ValueError('created ID namespace in style/script requires explicit supported references')
    # Namespaced fragments must use conventional quoted XML attributes; parsing
    # below proves every actual ID was renamed and all remaining bytes survived.
    pattern=r'(\s)([\w:-]+)\s*=\s*([\"\'])(.*?)\3'
    # Preserve whitespace surrounding '=' as well as literal numeric attributes.
    def preserve(match):
        value=match[4]; name=match[2]
        if name=='id': new=mapping.get(value,value)
        elif name.rsplit(':',1)[-1]=='href' and value.startswith('#'): new='#'+mapping.get(value[1:],value[1:])
        elif name in {'fill','stroke','filter','clip-path','mask','marker-start','marker-mid','marker-end','style'}:
            new=re.sub(r'url\(\s*([\"\']?)#([^\s)\"\']+)\1\s*\)',lambda m:m.group(0).replace('#'+m[2],'#'+mapping.get(m[2],m[2])),value)
        else: new=value
        start=match.start(4)-match.start();end=match.end(4)-match.start()
        return match[0][:start]+new+match[0][end:]
    changed=re.sub(pattern,preserve,fragment,flags=re.S)
    actual={n.get('id') for n in ET.fromstring('<g>'+changed+'</g>').iter() if n.get('id')}
    expected={mapping.get(n.get('id'),n.get('id')) for n in ET.fromstring('<g>'+fragment+'</g>').iter() if n.get('id')}
    if actual!=expected: raise ValueError('cannot namespace explicit fragment IDs without ambiguity')
    return changed


def canonicalize_capacity_program(program, current_svg, namespace):
    """Return a new program and exhaustive before/after log, or fail closed.

    Supported corrections: relocate one complete literal operation or an explicit
    top-level operation list; label unreferenced unnamed relations; move proven
    same-program-created top-level targets to created_target_ids. Namespace only
    defined program/check/result/created IDs and their typed references. No values,
    geometry, scientific content, crop review or source provenance are inferred.
    """
    raw=deepcopy(program); result=deepcopy(program); changes=[]; log=[]
    try:
        if not isinstance(program,dict): raise ValueError('program must be object')
        if not isinstance(namespace,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',namespace): raise ValueError('invalid namespace')
        if not isinstance(program.get('id'),str) or not program['id']: raise ValueError('program identity required')
        root=ET.parse(current_svg).getroot() if isinstance(current_svg,(str,Path)) else current_svg
        existing={n.get('id') for n in root.iter() if n.get('id')}
        prefix=lambda name: namespace+'::'+name
        if result.get('route')=='module_program':
            args=result.get('args',{})
            if not isinstance(args,dict): raise ValueError('args must be object')
            wrappers=int('operations' in args)+int('operations' in result)+int('method' in args)
            if wrappers>1: raise ValueError('conflicting operation wrappers')
            if 'method' in args:
                if not _operation(args): raise ValueError('flat operation must be a complete literal')
                result['args']={'operations':[deepcopy(args)]}
                changes.append({'kind':'relocate_complete_literal_operation','from':'args','to':'args.operations[0]'})
            elif 'operations' in result:
                if args or not isinstance(result['operations'],list) or not all(_operation(o) for o in result['operations']): raise ValueError('conflicting or incomplete top-level operations')
                result['args']={'operations':result.pop('operations')}
                changes.append({'kind':'relocate_complete_literal_operations','from':'operations','to':'args.operations'})
            scope=_compile_typed_scope(result,root)
            declared=result.get('target_ids')
            if not isinstance(declared,list) or not declared or any(not isinstance(i,str) for i in declared): raise ValueError('explicit target_ids required')
            fresh=set(declared)-existing; created=set(scope['created_ids'])
            if fresh-created: raise ValueError('unknown declared target not explicitly created by this program')
            ops=list(_operations(result.get('args',{}).get('operations',[])))+list(_operations(result.get('convergence',{}).get('repairs',[])))
            if fresh:
                anchors={o.get('args',{}).get('parent_id') for o in ops if o.get('method')=='bp_add'}
                if not anchors & set(declared) & set(scope['existing_write_ids']) & existing:
                    raise ValueError('created target requires a retained existing parent write anchor')
                if 'created_target_ids' in result and set(result['created_target_ids'])!=fresh: raise ValueError('conflicting created target declarations')
                result['target_ids']=[i for i in declared if i in existing]
                result['created_target_ids']=[i for i in declared if i in fresh]
                changes.append({'kind':'classify_proven_created_targets','ids':sorted(fresh),'existing_write_anchors':sorted(anchors & set(declared) & existing)})
            created_map={i:prefix(i) for i in sorted(created)}
            if set(created_map.values()) & existing: raise ValueError('namespaced created ID already exists')
        else:
            # Generated source code is opaque and never rewritten or interpreted.
            created_map={};ops=[]
        relations=result.get('relations',[])
        convergence=result.get('convergence',{})
        if not isinstance(relations,list) or not isinstance(convergence,dict): raise ValueError('invalid relations/convergence')
        checks=convergence.get('alignment_checks',[])
        repairs=convergence.get('repairs',[])
        if not isinstance(checks,list) or not isinstance(repairs,list): raise ValueError('invalid convergence lists')
        explicit=[r['id'] for r in relations+checks if isinstance(r,dict) and isinstance(r.get('id'),str) and r['id']]
        if len(explicit)!=len(set(explicit)): raise ValueError('ambiguous duplicate relation/check IDs')
        referenced=[r.get('check_id') for r in repairs]
        if any(ref not in explicit for ref in referenced): raise ValueError('ambiguous convergence check_id cannot name a missing relation')
        check_map={i:prefix(i) for i in explicit}
        for index,relation in enumerate(relations):
            if not isinstance(relation,dict): raise ValueError('relation must be object')
            if 'id' in relation and (not isinstance(relation['id'],str) or not relation['id'].strip()):
                raise ValueError('explicit relation identity must be nonempty text')
            if not relation.get('id'):
                local=f'relation-{index:04d}'
                if local in explicit: raise ValueError('ambiguous generated relation identity')
                relation['id']=prefix(local)
                changes.append({'kind':'label_unreferenced_relation','index':index,'id':relation['id']})
            else: relation['id']=check_map[relation['id']]
        for check in checks:
            if not isinstance(check,dict) or check.get('id') not in check_map: raise ValueError('alignment check requires explicit identity')
            check['id']=check_map[check['id']]
        for repair in repairs: repair['check_id']=check_map[repair['check_id']]
        operation_ids=[o['id'] for o in ops if o.get('id') is not None]
        if any(not isinstance(i,str) or not i for i in operation_ids) or len(operation_ids)!=len(set(operation_ids)) or program['id'] in operation_ids: raise ValueError('ambiguous operation result identities')
        deps=result.get('depends_on',[])
        if not isinstance(deps,list) or any(not isinstance(i,str) or not i for i in deps): raise ValueError('invalid dependencies')
        results_map={i:prefix(i) for i in [program['id']]+deps+operation_ids}
        result['id']=results_map[program['id']]
        result['depends_on']=[results_map[i] for i in deps]
        if result.get('when'):
            trigger=result['when']
            if trigger.get('program') not in deps: raise ValueError('conditional trigger requires explicit dependency')
            trigger['program']=results_map[trigger['program']]
        for op in ops:
            if op.get('id') is not None: op['id']=results_map[op['id']]
        id_fields={'target_ids','created_target_ids','neighbor_ids','read_ids','reference_ids','container_ids','subject_id','object_id','parent_id','before_id','after_id'}
        def rewrite(value,key=None):
            if key in id_fields:
                if isinstance(value,str): return created_map.get(value,value)
                if isinstance(value,list): return [rewrite(i,key) for i in value]
            if isinstance(value,dict):
                copy={k:rewrite(v,k) for k,v in value.items()}
                if '$measure' in copy:
                    spec=copy['$measure']; spec['ids']=[created_map.get(i,i) for i in spec.get('ids',[])]
                if '$result' in copy:
                    spec=copy['$result']; step=spec.get('step')
                    if step not in results_map: raise ValueError('unknown operation/program result reference')
                    spec['step']=results_map[step]
                if copy.get('method')=='bp_add': copy['args']['svg']=_rewrite_fragment(copy['args']['svg'],created_map)
                return copy
            if isinstance(value,list): return [rewrite(v) for v in value]
            return value
        result=rewrite(result)
        if result.get('route')=='module_program': _compile_typed_scope(result,root)
        changes.append({'kind':'namespace_explicit_identities','program_and_result_ids':results_map,'created_ids':created_map,'check_ids':check_map})
        log.append({'before':raw,'after':deepcopy(result),'changes':changes,'semantic_values_inferred':False})
        return result,log
    except (ValueError,KeyError,TypeError,ET.ParseError) as exc:
        log.append({'before':raw,'after':deepcopy(result),'changes':changes,'rejected':str(exc)})
        raise ProgramContractError(str(exc),raw,log) from exc
