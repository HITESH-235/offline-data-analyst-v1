"""Bounded entity mean -> column comparison -> equal-entity mean.

Inputs remain two raw frames until observations have been reduced to their
entity grain. The operation never consumes an arbitrary generated result table.
"""
import copy
import math
from numbers import Integral
import pandas as pd
from app.analysis.filtering import filter_data, column_comparison, parse_dates
from app.analysis.calendar import evaluate
from app.services.request_control import checkpoint


def columns(parameters):
    label=parameters.get('entity_label','Entities')
    return ['Classification','Comparable '+label,'Contributing '+label,
            'Missing Measurement '+label,parameters['measurement']['name']]


def expression_columns(node):
    if 'column' in node:return {node['column']}
    return set().union(*(expression_columns(arg) for arg in node.get('args',[])))


def resolve_source(p,source,catalog):
    """Complete omissions only; explicit parameters and the actual FK own the grain.

    Used at plan validation and rechecked before execution. Never infer a key,
    replace a conflicting declaration, or join an additional source.
    """
    from app.services.planned_analysis import join_identity
    names=[p['population_table'],p['observations_table']]
    declared=source.get('tables',[])
    extra=set(declared)-set(names)
    if extra:raise ValueError('entity_comparison has conflicting extra source tables: '+', '.join(sorted(extra)))
    if len(declared)!=len(set(declared)):raise ValueError('entity_comparison has duplicate source declarations')
    databases={n.split('::',1)[0] for n in names if '::' in n}
    if len(databases)!=1 or any('::' not in n for n in names):raise ValueError('entity_comparison requires explicit table IDs in the same SQLite database; cross-database sources are unsupported')
    if source.get('database') is not None and source['database'] not in databases:raise ValueError('entity_comparison source database conflicts with its explicit tables')
    edge={'from_table':names[1],'from_column':p['observation_key'],'to_table':names[0],'to_column':p['entity_key']}
    if source.get('join_keys') and join_identity(source['join_keys'])!=join_identity([edge]):raise ValueError('entity_comparison has a conflicting relationship; expected observation_key -> entity_key')
    if not any(all(e.get(k)==v for k,v in edge.items()) for e in catalog.get('relationships',[])):
        missing=set(names)-set(declared)
        detail='; missing sources cannot be resolved: '+', '.join(sorted(missing)) if missing else ''
        raise ValueError('entity_comparison requires a declared observation foreign key to the population entity key'+detail)
    tables=catalog.get('tables',{})
    needed={names[0]:{p['entity_key'],p['comparison']['column'],p['comparison']['value_column'],*[f['column'] for f in p.get('filters',[])]},
            names[1]:{p['observation_key'],*expression_columns(p['measurement']['expression'])}}
    for name,fields in needed.items():
        if not fields<=set(tables.get(name,{}).get('columns',[])):raise ValueError('entity_comparison references unknown columns in '+name)
    # Check the actual SQLite FK rather than trusting only a cached catalog edge.
    from app.services.dataset_manager import DatasetManager
    from pathlib import Path
    import sqlite3
    base=DatasetManager.get_dataset(None,names[0]);observations=DatasetManager.get_dataset(None,names[1])
    if not base or not observations or not base.table_name or not observations.table_name or base.filepath!=observations.filepath:
        raise ValueError('entity_comparison currently requires two tables in one SQLite database')
    quote=lambda value:'"'+value.replace('"','""')+'"'
    with sqlite3.connect(Path(base.filepath).resolve().as_uri()+'?mode=ro',uri=True) as db:
        keys=db.execute('PRAGMA foreign_key_list('+quote(observations.table_name)+')').fetchall()
        matches=[row for row in keys if row[2]==base.table_name and row[3]==p['observation_key'] and row[4]==p['entity_key']]
        if len(matches)!=1 or sum(row[0]==matches[0][0] for row in keys)!=1:raise ValueError('entity_comparison supports one declared single-column foreign key only')
    return {'tables':names,'join_keys':[edge]}


def resolve_plan_sources(plan):
    """Resolve each staged output without changing another output's population."""
    from app.analysis.operations import ContractError
    from app.services.metadata_service import MetadataService
    staged=[(i,out) for i,out in enumerate(plan['outputs']) if out['kind']=='entity_comparison']
    if not staged:return plan
    catalog=MetadataService.get_catalog_index()
    inherited=[]
    for i,out in staged:
        try:resolved=resolve_source(out['parameters'],out.get('source') or plan['source'],catalog)
        except ValueError as error:raise ContractError(f'$.analysis_plan.outputs[{i}].source',str(error)) from None
        if out.get('source'):out['source']=resolved
        else:inherited.append((out,resolved))
    # A shared default can be updated only when every consumer agrees. Otherwise
    # materialize the staged output override and retain the other populations.
    if len(inherited)==len(plan['outputs']) and all(src==inherited[0][1] for _,src in inherited):
        plan['source']=inherited[0][1]
    else:
        for out,src in inherited:out['source']=src
    return plan


def _key_family(series):
    values=series.dropna()
    if values.empty:return None
    if values.map(lambda v:isinstance(v,str)).all():return 'text'
    if values.map(lambda v:isinstance(v,Integral) and not isinstance(v,bool)).all():return 'integer'
    raise ValueError('entity keys must be nonnull text or integer identifiers; key coercion is unsupported')


def calculate(frames,parameters):
    from app.analysis.operations import validate
    p=validate('entity_comparison',parameters)
    if not isinstance(frames,dict) or set(frames)!={p['population_table'],p['observations_table']}:
        raise ValueError('entity_comparison requires separate raw population and observation frames, never a flattened join')
    base=frames[p['population_table']];observations=frames[p['observations_table']]
    ek,ok=p['entity_key'],p['observation_key'];measurement=p['measurement'];rule=p['comparison']
    required={ek,rule['column'],rule['value_column']}
    leaves=expression_columns(measurement['expression'])
    if not required<=set(base) or not ({ok}|leaves)<=set(observations):raise ValueError('entity comparison columns or keys are missing')
    if base[ek].isna().any() or base[ek].duplicated().any():raise ValueError('population entity key must be unique and nonnull before filtering')
    if observations[ok].isna().any():raise ValueError('observation entity keys must be nonnull')
    left_type,right_type=_key_family(base[ek]),_key_family(observations[ok])
    if left_type and right_type and left_type!=right_type:raise ValueError('population and observation key types are incompatible')
    if not observations[ok].isin(base[ek]).all():raise ValueError('observation keys violate the declared population relationship')
    # Validate full comparison columns even if the selected population is empty.
    column_comparison(base,rule)
    for f in p.get('filters',[]):
        if f.get('value_column') and {f['column'],f['value_column']}=={rule['column'],rule['value_column']}:
            raise ValueError('classification comparison cannot also filter the population')
    selected=filter_data(base,p.get('filters',[])).reset_index(drop=True)
    numeric=observations.copy();usable=pd.Series(True,index=numeric.index)
    for col in leaves:
        values=numeric[col].dropna()
        if not values.map(lambda v:isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)).all():raise ValueError('measurement inputs must contain finite numeric values or null')
        usable &= numeric[col].notna()
    checkpoint()
    values=evaluate(measurement['expression'],numeric.loc[usable])
    if not isinstance(values,pd.Series):values=pd.Series(values,index=numeric.index[usable],dtype=float)
    staged=pd.DataFrame({'key':numeric[ok].to_numpy(),'value':float('nan')})
    staged.loc[usable.to_numpy(),'value']=values.to_numpy()
    first=staged.groupby('key',sort=False,dropna=False).agg(records=('value','size'),usable=('value','count'),mean=('value','mean')).reset_index()
    if first['key'].duplicated().any():raise ValueError('first-stage aggregation did not produce unique entity keys')
    # Isolate all internal names from user columns; join only key/mean/coverage.
    entities=pd.DataFrame({'key':selected[ek].to_numpy()}).merge(first,on='key',how='left',validate='one_to_one',sort=False)
    if len(entities)!=len(selected) or not entities['key'].equals(pd.Series(selected[ek].to_numpy(),name='key')):
        raise ValueError('entity join changed the selected population grain or order')
    actual,estimated=selected[rule['column']],selected[rule['value_column']]
    if rule['value_type']=='date':actual,estimated=parse_dates(actual,rule['column']),parse_dates(estimated,rule['value_column'])
    comparable=actual.notna() & estimated.notna();matched=column_comparison(selected,rule)
    no_records=entities['records'].isna();no_usable=entities['records'].notna() & (entities['usable']==0)
    contributing=entities['mean'].notna();missing_measurement=no_records | no_usable
    cols=columns(p);rows=[];groups=[]
    for name,mask in [(p.get('matched_label','Matched'),comparable & matched),(p.get('unmatched_label','Not matched'),comparable & ~matched)]:
        count=int(mask.sum());included=mask & contributing;n=int(included.sum())
        mean=float(entities.loc[included,'mean'].mean()) if n else None
        f={'classification':name,'comparable_count':count,'contributing_count':n,
           'missing_measurement_count':int((mask & missing_measurement).sum()),
           'missing_record_count':int((mask & no_records).sum()),'unusable_measurement_count':int((mask & no_usable).sum()),
           'mean':mean,'entity_mean_sum':float(entities.loc[included,'mean'].sum()) if n else 0.}
        if count!=n+f['missing_measurement_count']:raise ValueError('classification denominator does not reconcile')
        groups.append(f);rows.append(dict(zip(cols,[name,count,n,f['missing_measurement_count'],mean])))
    missing_actual=int(actual.isna().sum());missing_estimated=int((actual.notna() & estimated.isna()).sum())
    total_comparable=int(comparable.sum());total_contributing=int((comparable & contributing).sum())
    if len(selected)!=missing_actual+missing_estimated+total_comparable:raise ValueError('date exclusions do not partition the population')
    checkpoint()
    audit={'parameters':copy.deepcopy(p),'entity_key':ek,'observation_key':ok,
        'first_stage':{'aggregation':'mean','expression':measurement['expression'],'key':ok,'observation_rows':len(observations),
                       'entities_with_records':len(first),'selected_observation_rows':int(entities['records'].fillna(0).sum()),'usable_observations':int(usable.sum()),'duplicate_observations':'retained; repeated rows participate in their entity mean'},
        'join':{'type':'left','cardinality':'one_to_one_after_preaggregation','base_unique':True,'first_stage_unique':True,
                'referential_integrity':True,'relationship':{'from_table':p['observations_table'],'from_column':ok,'to_table':p['population_table'],'to_column':ek},'key_type':left_type or right_type,'input_base_entities':len(base),'selected_entities':len(selected),'joined_entities':len(entities)},
        'population_filters':p.get('filters',[]),'comparison_rule':rule,
        'second_stage':{'aggregation':'mean','weighting':'equal_entity','input':'one mean per contributing entity'},
        'population_count':len(selected),'comparable_count':total_comparable,'contributing_count':total_contributing,
        'missing_actual_count':missing_actual,'missing_comparison_count':missing_estimated,
        'missing_record_count':int((comparable & no_records).sum()),'unusable_measurement_count':int((comparable & no_usable).sum()),
        'missing_measurement_count':int((comparable & missing_measurement).sum()),
        'date_excluded_without_measurement_count':int((~comparable & missing_measurement).sum()),
        'exclusion_definition':'Missing actual across the filtered population; missing comparison only among entities with actual values. Measurement exclusions only among comparable entities. Date-excluded missing measurements are overlap information, not an additional exclusion.',
        'groups':groups,'reconciled':True}
    return {'analysis_kind':'entity_comparison','columns':cols,'data':rows,'row_count':2,
        'source_observation_count':len(selected),'units':{measurement['name']:measurement['unit']} if measurement.get('unit') else {},
        'entity_audit':audit,'measure_provenance':{cols[1]:{'operation':'comparable_count'},cols[2]:{'operation':'contributing_count'},cols[3]:{'operation':'missing_measurement_count'},cols[4]:{'operation':'mean_of_entity_means','derived':measurement['expression'],'weighting':'equal_entity'}},
        'result_scope':{'full_group_count':2,'returned_row_count':2,'limit':None,'sort_by':None,'ascending':True},
        'visualization_blueprint':{'chart_type':'bar','x':cols[0],'y':cols[4],'title':measurement['name']+' by comparison classification'}}
