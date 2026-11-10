"""Execute validated named operations and bind their publication requirements."""
from app.services.request_control import checkpoint, phase
import copy
from app.analysis.operations import validate, execute, ContractError
from app.services.dataset_manager import DatasetManager
from app.llm.table_selector import TableSelector
from app.services.metadata_service import MetadataService

class UnsupportedOperation(ValueError):pass

def join_identity(keys):
    return sorted(tuple(sorted(((k['from_table'],k['from_column']),(k['to_table'],k['to_column'])))) for k in keys)

def validate_context(plan,history,reference=None,changed_fields=()):
    """Compare structured state only; language interpretation belongs to planning."""
    from app.services.specification_context import validate_followup
    validate_followup(plan,history,reference,changed_fields)

def validate_columns(kind,p,source,catalog):
    from app.analysis.entity_comparison import expression_columns
    available=set().union(*(set(catalog.get(name,{}).get('columns',[])) for name in source['tables']))
    needed=set(p.get('group_by',[]))
    for predicate in p.get('filters',p.get('eligibility_filters',[])):
        needed.add(predicate['column'])
        if predicate.get('value_column'):needed.add(predicate['value_column'])
    if kind=='aggregation':needed.update(m['column'] for m in p['measures'])
    elif kind=='calendar_aggregate':
        needed.add(p['date_column'])
        if p['metric'].get('expression'):needed.update(expression_columns(p['metric']['expression']))
    elif kind=='comparison_summary':needed.update([p['column'],p['value_column']])
    elif kind in {'statistics','correlation'}:needed.update(p.get('columns') or [])
    if needed-available:raise ContractError('$.analysis_plan.parameters','unknown source columns: '+', '.join(sorted(needed-available)))

def run(plan,db,emit):
    from app.services.analysis_package import OutputAccumulator
    outputs=OutputAccumulator();steps=[]
    catalog=MetadataService.get_catalog_index().get('tables',{})
    emit('selecting_tables')
    from app.analysis.operations import output_contract
    from app.analysis.entity_comparison import resolve_plan_sources
    resolve_plan_sources(plan)
    contract=output_contract(plan)
    cache={}
    for i,out in enumerate(plan['outputs']):
        checkpoint()
        with phase('source_validation',out['id']) as source_timing:
            src=out.get('source') or plan['source']
            names=src['tables'];databases={name.split('::',1)[0] for name in names if '::' in name}
            if len(databases)>1:raise UnsupportedOperation('Cross-database joins are not supported. Select tables from one SQLite database with declared relationships. No cross-database result or identifier mapping was calculated.')
            selection=TableSelector.resolve_selection({'tables_needed':names,'join_keys':src.get('join_keys',[])},catalog,names[0],src.get('database'))
            TableSelector.validate_selection(selection,catalog)
            source={'tables':selection['tables_needed'],'join_keys':selection.get('join_keys',[])}
            # Persist the resolved plan that actually executed, including exact IDs.
            if out.get('source'):out['source']=copy.deepcopy(source)
            else:plan['source']=copy.deepcopy(source)
            # Qualified source IDs in the contract must match the validated source exactly.
            contract['outputs'][i]['source_tables']=source['tables']
            params=validate(out['kind'],out['parameters'],f'$.analysis_plan.outputs[{i}].parameters')
            validate_columns(out['kind'],params,source,catalog)
            if out['kind']=='calendar_aggregate':
                nested=params.get('source')
                if nested and (set(nested['tables'])!=set(source['tables']) or join_identity(nested.get('join_keys',[]))!=join_identity(source['join_keys'])):raise ContractError(f'$.analysis_plan.outputs[{i}].parameters.source','conflicts with the validated operation source')
                params['source']=source
        emit('running_tool')
        step={'tool':out['kind'],'parameters':params,'status':'failed','output_id':out['id'],**source}
        try:
            key=repr(source)
            with phase('data_loading',out['id']) as load_timing:
                if out['kind']=='entity_comparison':
                    key=('separate_entity_sources',key)
                    if key not in cache:
                        cache[key]={name:DatasetManager.load_dataset_dataframe(DatasetManager.get_dataset(db,name)) for name in source['tables']}
                elif key not in cache:
                    if len(source['tables'])==1:
                        dataset=DatasetManager.get_dataset(db,source['tables'][0]);cache[key]=DatasetManager.load_dataset_dataframe(dataset)
                    else:cache[key]=DatasetManager.load_joined_dataframe(source['tables'],source['join_keys'])
            with phase('calculation',out['id']) as calculation_timing:
                result=execute(out['kind'],params,cache[key])
            with phase('output_verification',out['id']) as verification_timing:
                outputs.record(out['kind'],params,result,source,len(steps),out['id'],contract)
            step['timings_ms']={r['phase']:r['duration_ms'] for r in (source_timing,load_timing,calculation_timing,verification_timing)}
        except (ValueError,TypeError,KeyError) as error:
            step['error']=str(error);steps.append(step)
            return {'failed':True,'type':'text','content':str(error),'analysis_outputs':outputs.export(),'calculation':{'steps':steps}},contract
        step['status']='succeeded';steps.append(step)
    emit('preparing_answer')
    result={'type':'table','content':'','analysis_outputs':outputs.export(),'calculation':{'steps':steps}}
    if outputs.tables:
        result['results']=outputs.tables[0]['result']
        if result['results'].get('analysis_context'):result['analysis_context']=result['results']['analysis_context']
    return result,contract
