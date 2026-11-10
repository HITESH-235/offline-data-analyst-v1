"""Typed change permissions over the existing canonical specification, not English."""
import copy
from app.analysis.operations import AnalysisPlan,PlannedOutput,REGISTRY,ContractError

_MISSING=object()

def instructions():
    sections=[name for name in AnalysisPlan.model_fields if name!='outputs']
    return ('changed_fields uses dot paths relative to the stored specification. Whole sections or precise fields are allowed: '
            +', '.join(sections)+', outputs.<stable output id>.source, outputs.<stable output id>.parameters. '
            'Descendants must exist in the typed schema; list indices are zero-based and must exist before or after the change. '
            'Parameter aliases declared in the operation schema resolve to their canonical field only when unique. Indices address the stored baseline; reordered predicates must have an unambiguous structural match. '
            'Optional typed fields (such as limit) may be added or removed. Output ids and kinds are immutable. '
            'Parameter-only shorthand is allowed only for a single unambiguous output. '
            'Changing source affects inherited sources only. Table limits, chart scope and chat presentation have independent permissions.')


def _resolve(schema,defs,tokens,values,check_indices):
    if not tokens:return [],True
    if '$ref' in schema:return _resolve(defs[schema['$ref'].split('/')[-1]],defs,tokens,values,check_indices)
    variants=schema.get('anyOf') or schema.get('oneOf')
    if variants:
        results=[]
        for branch in variants:
            resolved=defs.get(branch.get('$ref','').split('/')[-1],branch)
            required=resolved.get('required',[])
            if required and not any(isinstance(v,dict) and set(required)<=v.keys() for v in values):continue
            results.append(_resolve(branch,defs,tokens,values,check_indices))
        valid={tuple(path) for path,ok in results if ok}
        if len(valid)==1:return list(next(iter(valid))),True
        return (results[0][0] if results else tokens),False
    token,*rest=tokens
    if schema.get('type')=='array':
        if not token.isdecimal() or str(int(token))!=token:return tokens,False
        index=int(token);members=[v[index] for v in values if isinstance(v,list) and index<len(v)]
        resolved,valid=_resolve(schema.get('items',{}),defs,rest,members,check_indices)
        return [token,*resolved],valid and (bool(members) or not check_indices)
    from app.analysis.field_ownership import ownership
    props=schema.get('properties',{});owners=ownership(props).get(token,set())
    if len(owners)>1:raise ValueError('ambiguous field '+repr(token)+'; canonical fields: '+', '.join(sorted(owners)))
    if owners:
        owner=next(iter(owners));children=[v[owner] for v in values if isinstance(v,dict) and owner in v]
        resolved,valid=_resolve(props[owner],defs,rest,children,check_indices)
        return [owner,*resolved],valid
    additional=schema.get('additionalProperties')
    if isinstance(additional,dict):
        children=[v[token] for v in values if isinstance(v,dict) and token in v]
        resolved,valid=_resolve(additional,defs,rest,children,check_indices)
        return [token,*resolved],valid
    return tokens,False


def _valid(model,tokens,values,check_indices,where,prefix):
    schema=model.model_json_schema()
    try:resolved,valid=_resolve(schema,schema.get('$defs',{}),tokens,values,check_indices)
    except ValueError as error:raise ContractError(where,str(error)) from None
    canonical='.'.join([*prefix,*resolved])
    if not valid:raise ContractError(where,'unknown field or invalid index; canonical path expected at this location: '+canonical)
    return canonical


def permissions(plan,changed_fields,prior=None,*,check_indices=True,expand_sources=False):
    """Validate declarations and return exact permissions in the comparison view."""
    before=prior or plan
    from app.services.output_identity import index_outputs
    old=index_outputs(before['outputs']);new=index_outputs(plan['outputs'])
    permitted=[]
    for i,path in enumerate(changed_fields):
        where=f'$.changed_fields[{i}]'
        tokens=path.split('.')
        if not path or any(not t for t in tokens):raise ContractError(where,'use a nonempty typed change path')
        root=tokens[0]
        if root in AnalysisPlan.model_fields and root!='outputs':
            model=AnalysisPlan.model_fields[root].annotation
            values=[before.get(root),plan.get(root)]
            canonical=_valid(model,tokens[1:],values,check_indices,where,[root])
            permitted.append(canonical)
            if root=='source' and expand_sources:
                suffix='.'.join(canonical.split('.')[1:])
                for key in old.keys()&new.keys():
                    if not old[key].get('source') and not new[key].get('source'):
                        permitted.append(f'outputs.{key}.source'+('.'+suffix if suffix else ''))
            continue
        if root!='outputs':
            if len(old)!=1 or len(new)!=1:raise ContractError(where,'parameter shorthand requires one unambiguous output; use outputs.<id>.parameters')
            key=next(iter(new));tokens=['outputs',key,'parameters',*tokens]
        if len(tokens)<3 or tokens[1] not in old or tokens[1] not in new:raise ContractError(where,'unknown or ambiguous output in '+path)
        key=tokens[1];section=tokens[2]
        if old[key]['kind']!=new[key]['kind']:raise ContractError(where,'operation kinds cannot change in a follow-up')
        if section=='parameters':model=REGISTRY[new[key]['kind']]
        elif section in PlannedOutput.model_fields and section not in {'id','kind'}:
            # source is an optional typed model, recovered from its non-null union.
            import typing
            annotation=PlannedOutput.model_fields[section].annotation
            model=next((t for t in typing.get_args(annotation) if hasattr(t,'model_json_schema')),annotation)
        else:raise ContractError(where,'output identities/kinds are immutable; use a typed source or parameters path')
        values=[old[key].get(section),new[key].get(section)]
        if section=='parameters':
            from app.analysis.operations import validate
            values=[validate(old[key]['kind'],old[key]['parameters']),validate(new[key]['kind'],new[key]['parameters'])]
        if section=='source':values=[old[key].get(section) or before['source'],new[key].get(section) or plan['source']]
        permitted.append(_valid(model,tokens[3:],values,check_indices,where,tokens[:3]))
    return permitted
