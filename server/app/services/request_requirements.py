"""Structured custom/legacy output coverage. No natural-language interpretation.

New deterministic requests use operation-generated contracts exclusively.
"""
import copy
from app.analysis.operations import canonical, formula_identity

class RequestIncomplete(ValueError):pass

def semantic_parameters(kind, parameters):
    p=canonical(kind,parameters)
    if kind=='calendar_aggregate':p.pop('output',None)
    if kind=='comparison_summary':
        p.setdefault('value_type','number')
        # Labels cannot turn a different formula into a match.
        for key in ('matched_label','count_label','comparison_label'):p.pop(key,None)
        from datetime import date, timedelta
        for predicate in p.get('eligibility_filters',[]):
            if predicate.get('operator')=='<=' and predicate.get('date_part')=='date' and predicate.get('value_type')=='date':
                predicate.update(operator='<',value=(date.fromisoformat(predicate['value'])+timedelta(days=1)).isoformat())
        p['eligibility_filters']=sorted(p.get('eligibility_filters',[]),key=lambda v:repr(sorted(v.items())))
        if not p.get('group_by'):p.pop('sort_by',None);p.pop('ascending',None)
        elif p.get('sort_by') is None:p.pop('ascending',None)
    return p


def _same_parameters(kind, left, right):
    try:return semantic_parameters(kind,left)==semantic_parameters(kind,right)
    except (ValueError,TypeError,KeyError):return False


def _source_matches(spec, source):
    from app.services.planned_analysis import join_identity
    return (not spec.get('source_tables') or set(spec['source_tables'])==set(source.get('tables',[]))) and (
        'join_keys' not in spec or join_identity(spec['join_keys'])==join_identity(source.get('join_keys',[])))


def validate_plan_request(envelope, requirement):
    if not requirement or envelope.get('unsupported_reason') or envelope.get('context_action')=='clarify':return
    if requirement.get('unresolved'):raise RequestIncomplete(requirement['unresolved'])
    validate_structured_plan(envelope, requirement)
    if envelope.get('intent')=='CONVERSATION':raise RequestIncomplete('The requested calculation cannot be completed as conversation without verified outputs.')
    plan=envelope.get('analysis_plan')
    if not plan:
        # Custom Python has no deterministic plan; its exports are checked at
        # publication. SIMPLE requests without a plan are rejected by dispatch.
        return
    for spec in requirement['outputs']:
        def matches(out):
            return out['kind']==spec['kind'] and _source_matches(spec,out.get('source') or plan['source']) and (
                'parameters' not in spec or _same_parameters(spec['kind'],out['parameters'],spec['parameters']))
        if not any(matches(out) for out in plan['outputs']):
            if spec['kind']=='calendar_aggregate':
                expected=semantic_parameters(spec['kind'],spec['parameters'])
                actual=next((semantic_parameters(o['kind'],o['parameters']) for o in plan['outputs'] if o['kind']==spec['kind'] and _source_matches(spec,o.get('source') or plan['source'])),None)
                differences=[]
                if actual is None:differences.append('calculation type or joined sources')
                else:
                    for key,label in [('date_column','date column'),('years','year'),('grain','calendar grouping'),('filters','population filters')]:
                        if expected.get(key)!=actual.get(key):differences.append(label)
                    for key,label in [('expression','formula'),('aggregation','aggregation'),('unit','currency unit'),('name','measure label')]:
                        if expected['metric'].get(key)!=actual['metric'].get(key):differences.append(label)
                raise RequestIncomplete('The plan does not match the requested calendar calculation: '+', '.join(differences or ['calculation scope'])+'. No calculation was run.')
            raise RequestIncomplete('Requested '+spec['id']+' was not planned: preserve every comparison measure, grouping, population, formula, source and requested percentage sorting. A counts-only or count-sorted approximation cannot satisfy it.')


def publication_checks(requirement,tables,observations=()):
    if not requirement:return []
    if requirement.get('unresolved'):return [{'requirement_id':'request','status':'missing','reason':requirement['unresolved'],'table_ids':[]}]
    from app.analysis.operations import matches
    from app.services.analysis_package import _matches,requirement_mismatch_reason
    checks=[]
    for spec in requirement['outputs']:
        found=[];mismatches=[]
        for table in tables:
            r=table['result'];kind=spec['kind']
            if table['tool']!=kind or not _source_matches(spec,table['source']):continue
            if 'parameters' in spec:
                if not _same_parameters(kind,table['parameters'],spec['parameters']):continue
                if not matches(kind,table['parameters'],r):continue
            if not _matches({k:v for k,v in spec.items() if k not in {'parameters','join_keys'}},table):
                mismatches.append(requirement_mismatch_reason(spec,table))
                continue
            if kind=='comparison_summary' and spec.get('parameters',{}).get('group_by'):
                scope=r.get('result_scope',{})
                if scope.get('limit') is not None or scope.get('full_group_count')!=len(r['data']):continue
                formula=r.get('comparison_audit',{}).get('percentage_formula',{})
                if not {formula.get('numerator'),formula.get('denominator')}<=set(r['columns']):continue
                if spec['parameters'].get('sort_by')=='percentage':
                    percentage=next((c for c in r['columns'] if r.get('units',{}).get(c)=='%'),None)
                    if not percentage or scope.get('sort_by')!=percentage or scope.get('nulls')!='last':continue
                    values=[row[percentage] for row in r['data']];numeric=[v for v in values if v is not None]
                    if values!=sorted(numeric,reverse=not spec['parameters'].get('ascending',False))+[None]*(len(values)-len(numeric)):continue
            found.append(table['id'])
        if spec['kind']=='statistics':
            for observation in observations:
                if observation['tool']!='statistics' or not _source_matches(spec,observation['source']):continue
                if spec.get('parameters') and not matches('statistics',spec['parameters'],observation['result']):continue
                stats=observation['result'].get('statistics',{})
                if all(c in stats for c in spec.get('columns',[])) and all(m.get('source_column') in stats and m.get('operation') in stats[m['source_column']] for m in spec.get('measures',[])):
                    found.append(spec['id'])
        checks.append({'requirement_id':spec['id'],'status':'passed' if found else 'missing','table_ids':found,
                       'reason':'' if found else ' '.join(dict.fromkeys(mismatches)) if mismatches else 'Requested measures/grouping/population/formula/source/sorting were not verified together: '+spec['id']})
    return checks


def validate_structured_plan(envelope, requirements):
    from app.services.planned_analysis import UnsupportedOperation
    from app.analysis.operations import canonical
    plan=envelope.get('analysis_plan')
    if not plan:
        # A grouping that has no source column or registered derivation has no
        # publication proof. Do not run arbitrary Python and imply success.
        from app.services.metadata_service import MetadataService
        tables=MetadataService.get_catalog_index().get('tables',{})
        for spec in requirements.get('outputs',[]):
            if spec['kind']=='entity_comparison':raise UnsupportedOperation('Entity comparison requires its registered deterministic plan. No calculation was run.')
            columns={c for t in spec.get('source_tables',[]) for c in tables.get(t,{}).get('columns',[])}
            if spec.get('source_tables') and spec.get('group_by') and any(c not in columns for c in spec['group_by']):
                raise UnsupportedOperation('This analysis needs staged calculations or derived groups that the current verification contract cannot support. No calculation was run. Please split it into supported analyses.')
        return
    from app.analysis.operations import covers_constraints
    for spec in requirements.get('outputs',[]):
        if 'parameters' in spec:continue
        if not any(out['kind']==spec['kind'] and _source_matches(spec,out.get('source') or plan['source']) and
                   covers_constraints(out['kind'],out['parameters'],spec) for out in plan['outputs']):
            raise RequestIncomplete('The plan omitted a requested measure, population, grouping, conversion, source, or result order. No substitute calculation was run.')
