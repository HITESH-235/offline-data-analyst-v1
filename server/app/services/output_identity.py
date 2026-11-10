"""Register output identities once; bind follow-ups to successful stored outputs."""
import copy
import uuid
from app.analysis.operations import ContractError

class OutputIdentityError(ContractError):pass


def index_outputs(outputs,where='$.analysis_plan.outputs'):
    indexed={}
    for output in outputs:
        identity=output.get('id')
        if not isinstance(identity,str) or not identity:raise OutputIdentityError(where,'a canonical output must have a registered identity')
        if identity in indexed:raise OutputIdentityError(where,'duplicate output identity '+identity)
        indexed[identity]=output
    return indexed


def referenced_spec(history,reference):
    prior=next((e for e in history.get('recent_successes',[]) if e['message_id']==reference),None)
    if not reference or prior is None:raise OutputIdentityError('$.reference_message_id','identify one successful stored specification; clarify a missing or ambiguous reference')
    plan=(prior.get('analysis') or {}).get('plan')
    if not plan:raise OutputIdentityError('$.reference_message_id','this saved result has no stable typed output identities; use a standalone specification')
    index_outputs(plan['outputs'])
    return plan


def resolve_outputs(value,history=None):
    """Consume structural references, leaving only canonical ids and paths.

    Supplied standalone ids are retained as registered legacy/local ids; omitted
    ids are allocated by the system. Once registered, spelling has no semantics.
    A compatibility rename needs an existing-id change-path anchor and exactly
    one unbound output on each side. Multi-output renames use explicit references.
    """
    result=copy.deepcopy(value)
    if not isinstance(result,dict) or result.get('context_action')=='clarify' or not isinstance(result.get('analysis_plan'),dict):return result
    plan=result['analysis_plan'];outputs=plan.get('outputs')
    if not isinstance(outputs,list) or any(not isinstance(o,dict) for o in outputs):return result
    inherit=result.get('context_action')=='inherit'
    if not inherit:
        for out in outputs:
            if out.get('reference_output_id'):raise OutputIdentityError('$.analysis_plan.outputs','output references require a successful follow-up baseline')
            out.pop('reference_output_id',None)
            if out.get('id') is None:out['id']='output_'+uuid.uuid4().hex
        index_outputs(outputs)
        return result
    prior=referenced_spec(history,result.get('reference_message_id')) if history is not None else None
    if prior is None:
        # Schema/repair snapshots lack project state. Consume explicit references,
        # but baseline-dependent reconciliation happens once at request planning.
        for out in outputs:
            ref=out.pop('reference_output_id',None)
            if ref:out['id']=ref
        index_outputs(outputs)
        return result
    existing=index_outputs(prior['outputs']);assigned=set();aliases={};pending=[]
    paths=result.get('changed_fields') or []
    anchors={key for key in existing if any(isinstance(p,str) and any(p=='outputs.'+key+'.'+section or p.startswith('outputs.'+key+'.'+section+'.') for section in ('parameters','source')) for p in paths)}
    def bind(out,target):
        draft=out.get('id')
        if target not in existing:raise OutputIdentityError('$.analysis_plan.outputs.reference_output_id','unknown stored output reference '+str(target))
        if target in assigned:raise OutputIdentityError('$.analysis_plan.outputs','multiple drafts reference the same stored output')
        if draft in existing and draft!=target:raise OutputIdentityError('$.analysis_plan.outputs','crossed output id and reference_output_id declarations')
        if out.get('kind')!=existing[target]['kind']:raise OutputIdentityError('$.analysis_plan.outputs','an output reference cannot change operation kind')
        if draft and draft!=target:
            if draft in aliases:raise OutputIdentityError('$.analysis_plan.outputs','ambiguous draft output alias')
            aliases[draft]=target
        out['id']=target;out.pop('reference_output_id',None);assigned.add(target)
    for out in outputs:
        ref=out.get('reference_output_id')
        if ref is not None:
            if not isinstance(ref,str) or not ref:raise OutputIdentityError('$.analysis_plan.outputs.reference_output_id','use a nonempty stored output identity')
            bind(out,ref)
        elif out.get('id') in existing:bind(out,out['id'])
        else:pending.append(out)
    unbound=set(existing)-assigned
    if pending:
        targets=unbound & anchors
        if len(pending)!=1 or len(unbound)!=1 or len(targets)!=1:
            raise OutputIdentityError('$.analysis_plan.outputs','cannot prove a unique output mapping; use reference_output_id for each existing output. Adding/removing outputs is unsupported in a follow-up')
        bind(pending[0],next(iter(targets)))
    if assigned!=set(existing) or len(outputs)!=len(existing):raise OutputIdentityError('$.analysis_plan.outputs','adding/removing outputs is unsupported in a follow-up; clarify a standalone calculation')
    resolved=[]
    for path in paths:
        matches=[(alias,target) for alias,target in aliases.items() if isinstance(path,str) and path.startswith('outputs.'+alias+'.')]
        if len(matches)>1:raise OutputIdentityError('$.changed_fields','ambiguous output reference in change path')
        if matches:
            alias,target=matches[0];path='outputs.'+target+path[len('outputs.'+alias):]
        resolved.append(path)
    result['changed_fields']=resolved
    index_outputs(outputs)
    return result
