"""Explicit scalar projections from verified grouped aggregates.

A projection is allowed only for one fully selected group, identical source,
operation, units and pre-existing predicates. Distinct counts are never summed.
"""
import copy
import json
from app.analysis.operations import canonical,matches,stamp

def _predicates(values):
    return [json.dumps(p,sort_keys=True) for p in values]

def bind(spec,parent):
    if spec['kind']!='aggregation' or parent['tool']!='aggregation':return None
    if spec.get('source_tables') and set(spec['source_tables'])!=set(parent['source'].get('tables',[])):return None
    base=parent['result'];p=parent['parameters']
    if not matches('aggregation',p,base):return None
    if spec.get('parameters'):
        target=copy.deepcopy(spec['parameters'])
    else:
        measures=spec.get('measures') or []
        if len(measures)!=1:return None
        m=measures[0]
        if m.get('derived') or not m.get('source_column') or not m.get('operation'):return None
        c=m['source_column'];target={'group_by':spec.get('group_by',[]),'aggregations':{c:m['operation']},'filters':spec.get('filters',[])}
        if m.get('output'):target['output_names']={c:m['output']}
        if 'divide_by' in m:target['transforms']=[{'column':c,'divide_by':m['divide_by'],'as':m.get('output',c),**({'unit':m['unit']} if m.get('unit') else {})}]
    if target.get('group_by') or target.get('limit') or len(target.get('aggregations',{}))!=1:return None
    groups=p.get('group_by',[])
    if not groups:return None
    source_column,operation=next(iter(target['aggregations'].items()))
    candidates=[(name,prov) for name,prov in base.get('measure_provenance',{}).items() if prov.get('source_column')==source_column and prov.get('operation')==operation]
    if len(candidates)!=1:return None
    name,prov=candidates[0]
    expected_transform=next((t for t in target.get('transforms',[]) if t['column']==source_column),None)
    if (prov.get('transform') or {}).get('divide_by')!=(expected_transform or {}).get('divide_by'):return None
    unit=(expected_transform or {}).get('unit')
    if base.get('units',{}).get(name)!=unit:return None
    old=_predicates(p.get('filters',[]));new=list(target.get('filters',[]))
    for predicate in old:
        index=next((i for i,v in enumerate(new) if json.dumps(v,sort_keys=True)==predicate),None)
        if index is None:return None
        new.pop(index)
    selection={}
    for condition in new:
        if set(condition)!={'column','operator','value'} or condition['operator']!='==' or condition['column'] not in groups or condition['value'] is None:return None
        if condition['column'] in selection:return None
        selection[condition['column']]=condition['value']
    if set(selection)!=set(groups):return None
    # Reuse literal/type validation; Python True == 1 must not bypass domain rules.
    try:
        import pandas as pd
        from app.analysis.filtering import filter_data
        filter_data(pd.DataFrame(base['data']),new)
    except (ValueError,TypeError):return None
    rows=[row for row in base['data'] if all(row[c]==v for c,v in selection.items())]
    populations=[x for x in base.get('group_populations',[]) if x['groups']==selection]
    if len(rows)!=1 or len(populations)!=1:return None
    output=(expected_transform or {}).get('as') or target.get('output_names',{}).get(source_column,source_column)
    new_prov=copy.deepcopy(prov)
    if new_prov.get('transform'):new_prov['transform']['as']=output
    result={'analysis_kind':'aggregation','columns':[output],'data':[{output:rows[0][name]}],'row_count':1,
            'measure_provenance':{output:new_prov},'units':{output:unit} if unit else {},
            'source_observation_count':populations[0]['count'],
            'result_scope':{'full_group_count':1,'returned_row_count':1,'limit':None,'sort_by':None,'ascending':True},
            'transformation_audit':{'fill_missing':{},'transforms':target.get('transforms',[]),'output_names':{source_column:output}},
            'binding':{'parent_table_id':parent['id'],'selection':selection,'projection':{name:output}}}
    stamp('aggregation',target,result)
    return {**copy.deepcopy(parent),'id':spec['id'],'label':spec['id'].replace('_',' ').title(),'parameters':target,
            'result':result,'signature':parent['signature']+';projection:'+spec['id']}
