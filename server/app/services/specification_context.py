"""One structural follow-up policy over successful canonical specifications."""
import copy
import json
from app.analysis.operations import canonical,validate,ContractError,Source,ChartScope,Presentation


def _state(plan):
    from app.services.planned_analysis import join_identity
    def source(value):
        result=Source.model_validate(value).model_dump(exclude_none=True)
        database=result.get('database')
        if database and all(name.startswith(database+'::') for name in result['tables']):result.pop('database')
        return result
    def parameters(out):
        result=canonical(out['kind'],out['parameters'])
        original=validate(out['kind'],out['parameters'])
        # Change paths index the stored predicate order, not a sorted digest.
        for field in ('filters','eligibility_filters'):
            if field in result:result[field]=copy.deepcopy(original.get(field,[]))
        return result
    return {'source':source(plan['source']),
            'chart_scope':ChartScope.model_validate(plan.get('chart_scope') or {}).model_dump(),
            'presentation':Presentation.model_validate(plan.get('presentation') or {}).model_dump(),
            'outputs':{o['id']:{'kind':o['kind'],'parameters':parameters(o),
                       'source':source(o.get('source') or plan['source'])} for o in plan['outputs']}}


def validate_followup(plan,history,reference,changed_fields):
    from app.services.output_identity import referenced_spec,resolve_outputs
    prior=referenced_spec(history,reference)
    resolved=resolve_outputs({'context_action':'inherit','reference_message_id':reference,'analysis_plan':plan,'changed_fields':list(changed_fields)},history)
    plan=resolved['analysis_plan'];changed_fields=resolved['changed_fields']
    before,after=_state(prior),_state(plan)
    from app.services.change_paths import permissions
    permitted=permissions(plan,changed_fields,prior,expand_sources=True)
    def walk(old,new,path):
        identity=lambda value:json.dumps(value,sort_keys=True,allow_nan=False)
        if identity(old)==identity(new):return
        if any(path==allowed or path.startswith(allowed+'.') for allowed in permitted):return
        if isinstance(old,dict) and isinstance(new,dict):
            for key in old.keys()|new.keys():walk(old.get(key),new.get(key),path+'.'+key if path else key)
        elif isinstance(old,list) and isinstance(new,list) and len(old)==len(new):
            if path.endswith('.join_keys'):
                from app.services.planned_analysis import join_identity
                if join_identity(old)==join_identity(new):return
            if all(isinstance(p,dict) and {'column','operator'}<=p.keys() for p in [*old,*new]):
                if sorted(map(identity,old))==sorted(map(identity,new)):return
                # Indices refer to the stored baseline. Align unchanged predicates
                # first, then unique structural owners; never guess among repeats.
                mapping={};used=set()
                for i,item in enumerate(old):
                    candidates=[j for j,value in enumerate(new) if identity(item)==identity(value)]
                    if len(candidates)==1 and sum(identity(x)==identity(item) for x in old)==1:
                        mapping[i]=candidates[0];used.add(candidates[0])
                signature=lambda p:identity({k:v for k,v in p.items() if k!='value'})
                for i,item in enumerate(old):
                    if i in mapping:continue
                    candidates=[j for j,value in enumerate(new) if j not in used and signature(item)==signature(value)]
                    owners=[k for k,value in enumerate(old) if k not in mapping and signature(value)==signature(item)]
                    if len(candidates)!=1 or len(owners)!=1:
                        raise ContractError('$.changed_fields','ambiguous predicate indices at '+path+'; declare the whole canonical collection or preserve unambiguous predicate ownership')
                    mapping[i]=candidates[0];used.add(candidates[0])
                new=[new[mapping[i]] for i in range(len(old))]
            for i,(a,b) in enumerate(zip(old,new)):walk(a,b,path+'.'+str(i))
        else:raise ContractError('$.analysis_plan.'+path,'follow-up changed an undeclared field; preserve it or clarify an explicit change')
    walk(before,after,'')
