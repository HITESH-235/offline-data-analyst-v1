"""Authoritative analysis outputs, completion requirements and factual rendering.

Presentation never creates/replaces calculation data. Completion is checked against
an explicit request contract; executing arbitrary Python is not a completion proof.
"""
import copy
import json
import math
import re

CALCULATIONS={'aggregation','calendar_aggregate','monthly_revenue','comparison_summary','correlation','statistics'}


def validate_table(result):
    if not isinstance(result,dict) or not isinstance(result.get('columns'),list) or not isinstance(result.get('data'),list):
        raise ValueError('A structured result requires columns and data rows.')
    columns=result['columns']
    if not columns or any(not isinstance(c,str) or not c for c in columns) or len(set(columns))!=len(columns):
        raise ValueError('Result columns must be distinct nonempty names.')
    if result.get('row_count',len(result['data']))!=len(result['data']):raise ValueError('Result row_count does not match its data.')
    for row in result['data']:
        if not isinstance(row,dict) or set(row)!=set(columns):raise ValueError('Every result row must match its declared columns.')
        for value in row.values():
            if isinstance(value,float) and not math.isfinite(value):raise ValueError('Result values must be finite or null.')
    json.dumps(result,allow_nan=False)


class OutputAccumulator:
    def __init__(self):
        self.tables=[]
        self.charts=[]
        self.observations=[]

    def record(self,tool,parameters,result,source,step_index,output_id=None,contract=None):
        if tool=='visualization':
            if parameters.get('chart_type') not in {'bar','line','scatter','histogram','box','heatmap'}:raise ValueError('Unsupported result chart type.')
            if not self.tables:raise ValueError('Calculate a structured result before requesting its chart.')
            table=next((t for t in self.tables if t['id']==output_id),None) if output_id else self.tables[-1]
            if table is None:raise ValueError('The chart references an unknown calculated output.')
            columns=table['result']['columns']
            if parameters.get('x') not in columns or parameters.get('y') is not None and parameters['y'] not in columns:
                raise ValueError('Chart fields must exist in the calculated result; charts cannot reload raw source rows.')
            self.charts.append({'id':f'chart-{len(self.charts)+1}','kind':'result','table_id':table['id'],'specification':copy.deepcopy(parameters)})
            return
        data=result.get('results') if tool=='run_code' else result
        if tool=='run_code' and result.get('verified_tables'):
            for entry in result['verified_tables']:
                self.record(entry['tool'],entry['parameters'],entry['result'],source,step_index,entry['id'],contract)
            return
        if data and data.get('columns') and isinstance(data.get('data'),list):
            validate_table(data)
            if len(json.dumps(data,allow_nan=False).encode())>3*1024*1024:
                raise ValueError('Calculated output exceeds the supported saved-result size; reduce the requested result explicitly. It was not silently truncated.')
            signature=json.dumps({'tool':tool,'parameters':parameters,'source':source,'output_id':output_id},sort_keys=True,default=str)
            if any(t['signature']==signature for t in self.tables):return
            candidate={'id':output_id or f'table-{len(self.tables)+1}','label':parameters.get('title') or tool.replace('_',' ').title(),
                                'result':copy.deepcopy(data),'source':copy.deepcopy(source),'tool':tool,'parameters':copy.deepcopy(parameters),
                                'step_index':step_index,'signature':signature}
            if contract:
                specs=[s for s in contract['outputs'] if s['id']==output_id] if output_id else [s for s in contract['outputs'] if _matches(s,candidate)]
                if len(specs)==1:
                    candidate['id']=specs[0]['id']
                    candidate['label']=specs[0]['id'].replace('_',' ').replace('-',' ').title()
                elif output_id:raise ValueError('Unknown requested output ID.')
            previous=next((t for t in self.tables if t['id']==candidate['id']),None)
            if previous and contract:
                spec=next((s for s in contract['outputs'] if s['id']==candidate['id']),None)
                if spec and not _matches(spec,candidate):raise ValueError('Invalid replacement cannot overwrite the last valid output.')
            if previous:self.tables[self.tables.index(previous)]=candidate
            else:self.tables.append(candidate)
        elif data:
            self.observations.append({'tool':tool,'parameters':copy.deepcopy(parameters),'result':copy.deepcopy(data),'source':copy.deepcopy(source),'step_index':step_index})

    def export(self):
        return {'tables':copy.deepcopy(self.tables),'charts':copy.deepcopy(self.charts),'observations':copy.deepcopy(self.observations)}


def validate_requirements(contract):
    if not isinstance(contract,dict) or set(contract)-{'outputs','chart_scope'} or not isinstance(contract.get('outputs'),list) or not contract['outputs']:
        raise ValueError('Completion contract requires a nonempty outputs list and optional chart_scope.')
    contract=copy.deepcopy(contract)
    allowed={'id','kind','columns','measures','group_by','scope','filters','source_tables'}
    for spec in contract['outputs']:
        if not isinstance(spec,dict) or set(spec)-allowed or not isinstance(spec.get('id'),str) or not spec.get('id') or spec.get('kind') not in CALCULATIONS|{'filtering'}:
            raise ValueError('Each requested output needs id/kind and only supported requirement fields.')
        for key in ('columns','group_by','source_tables','filters','measures'):
            if key in spec and not isinstance(spec[key],list):raise ValueError(f'{key} must be a list.')
            if key in ('columns','group_by','source_tables') and any(not isinstance(v,str) or not v for v in spec.get(key,[])):raise ValueError(f'{key} must contain nonempty field names.')
        if any(not isinstance(v,dict) for v in spec.get('filters',[])):raise ValueError('filters must contain predicate objects.')
        if spec['kind']=='aggregation':
            if 'group_by' not in spec or not spec.get('measures'):raise ValueError('Aggregation completion requires explicit group_by and requested measures, not only a tool name.')
            spec.setdefault('scope',{'mode':'all'});spec.setdefault('filters',[])
        scope=spec.get('scope',{})
        if not isinstance(scope,dict) or set(scope)-{'mode','limit'} or scope.get('mode','all') not in {'all','top'}:
            raise ValueError('Output scope must specify all or top, independently of chart_scope.')
        if scope.get('mode')=='top' and (type(scope.get('limit'))!=int or scope['limit']<1):raise ValueError('Top scope requires a positive limit.')
        for measure in spec.get('measures',[]):
            if not isinstance(measure,dict) or set(measure)-{'source_column','operation','output','unit','derived','divide_by'}:
                raise ValueError('Invalid measure requirement.')
            if spec['kind']=='aggregation' and not (measure.get('derived') or measure.get('source_column') and measure.get('operation')):raise ValueError('Each aggregate measure needs source_column/operation or a derived expression.')
            if not measure:raise ValueError('A measure requirement must identify the requested calculation.')
            for key in ('source_column','operation','output','unit'):
                if key in measure and (not isinstance(measure[key],str) or not measure[key]):raise ValueError(f'Measure {key} must be nonempty text.')
            if 'divide_by' in measure and (type(measure['divide_by']) not in (int,float) or not math.isfinite(measure['divide_by']) or measure['divide_by']==0):raise ValueError('Measure divide_by must be finite and nonzero.')
    if len({s['id'] for s in contract['outputs']})!=len(contract['outputs']):raise ValueError('Requested output IDs must be unique.')
    chart=contract.get('chart_scope',{})
    if not isinstance(chart,dict) or set(chart)-{'required','top_n'} or 'required' in chart and type(chart['required']) is not bool:raise ValueError('Invalid chart scope.')
    if 'top_n' in chart and chart['top_n'] not in (5,10,20):raise ValueError('Chart top_n must be 5, 10, or 20.')
    return copy.deepcopy(contract)


def _matches(spec,table):
    r=table['result']
    if spec['kind']!=r.get('analysis_kind',table['tool']):return False
    if spec['kind']=='statistics' and not r.get('statistics'):return False
    if any(c not in r['columns'] for c in spec.get('columns',[])):return False
    if spec.get('source_tables') and set(spec['source_tables'])!=set(table['source'].get('tables',[])):return False
    if spec.get('group_by') is not None and spec['group_by']!=table['parameters'].get('group_by',[]):return False
    population=r.get('comparison_audit',{}).get('parameters',{}).get('eligibility_filters',table['parameters'].get('filters',[]))
    if spec.get('filters') is not None and spec['filters']!=population:return False
    provenance=r.get('measure_provenance',{})
    for measure in spec.get('measures',[]):
        candidates=[(name,p) for name,p in provenance.items() if all(p.get(k)==measure[k] for k in ('source_column','operation') if k in measure)]
        if 'output' in measure:candidates=[(name,p) for name,p in candidates if name==measure['output']]
        if 'unit' in measure:candidates=[(name,p) for name,p in candidates if r.get('units',{}).get(name)==measure['unit']]
        if measure.get('derived'):candidates=[(name,p) for name,p in candidates if p.get('derived')==measure['derived']]
        if 'divide_by' in measure:candidates=[(name,p) for name,p in candidates if p.get('transform',{}).get('divide_by')==measure['divide_by']]
        if not candidates:return False
    scope=spec.get('scope')
    if scope and r.get('analysis_kind')=='aggregation':
        audit=r['result_scope']
        if scope['mode']=='all' and audit['returned_row_count']!=audit['full_group_count']:return False
        if scope['mode']=='top' and (audit['limit']!=scope['limit'] or audit['returned_row_count']!=min(scope['limit'],audit['full_group_count'])):return False
    return True


def _facts(table):
    r=table['result']
    return {'table_id':table['id'],'row_count':len(r['data']),'units':r.get('units',{}),
            'source_observation_count':r.get('source_observation_count'),
            'verification':r.get('verification'), 'comparison_audit':r.get('comparison_audit'),
            'result_scope':r.get('result_scope'),'transformation_audit':r.get('transformation_audit')}


def can_chart(result):
    data=result.get('data',[])
    if not data:return False
    if result.get('calendar_chart'):return True
    if result.get('correlation'):
        return any(isinstance(v,(int,float)) for row in result['correlation']['matrix'] for v in row)
    categories=[];numbers=[]
    for col in result['columns']:
        provenance=result.get('measure_provenance',{}).get(col,{})
        if re.search(r'(^id$|[_ .]id$|ID$|Id$|zip|postal)',col) and provenance.get('operation')!='count':continue
        values=[row[col] for row in data if row[col] is not None]
        if values and all(type(v) in (int,float) for v in values):numbers.append(col)
        elif values:categories.append(col)
    return bool(numbers and any(len({str(r[c]) for r in data})==len(data) for c in categories) or len(numbers)>=2 and len(data)>=2)


def render_table(result):
    kind=result.get('analysis_kind')
    if kind=='aggregation':
        from app.analysis.result_operations import explanation
    elif kind=='comparison_summary':
        from app.analysis.comparison_summary import explanation
    elif kind=='calendar_aggregate':
        from app.analysis.calendar import explanation
    elif kind=='monthly_revenue':
        from app.analysis.monthly_revenue import explanation
    elif kind=='correlation':
        from app.analysis.correlation import explanation
    else:
        columns=result['columns'];lines=['| '+' | '.join(columns)+' |','|'+'---|'*len(columns)]
        for row in result['data'][:20]:lines.append('| '+' | '.join(str(row[c]) if row[c] is not None else 'Unavailable' for c in columns)+' |')
        return f"Calculated result: {len(result['data'])} rows.\n\n"+'\n'.join(lines)
    return explanation(result)


def finalize(raw,question,project_id,package_id,contract=None):
    """One publication boundary for loop, deterministic and Python execution paths."""
    raw=copy.deepcopy(raw)
    if raw.get('clarification_required'):return raw
    outputs=raw.pop('analysis_outputs',None)
    if outputs is None:
        accumulator=OutputAccumulator()
        result=raw.get('results')
        steps=(raw.get('calculation') or {}).get('steps',[])
        step=next((s for s in reversed(steps) if s.get('status')=='succeeded' and s.get('tool')!='visualization'),{})
        if result:
            try:accumulator.record(step.get('tool','calculation'),step.get('parameters',{}),result,
                                   {'tables':step.get('tables',[]),'join_keys':step.get('join_keys',[])},max(len(steps)-1,0),contract=contract)
            except (ValueError,TypeError) as error:
                raw['failed']=True;raw['content']='Calculation output could not be published: '+str(error)
        outputs=accumulator.export()
    tables=outputs['tables'];reasons=[];checks=[];completed_observations=[]
    valid_tables=[]
    for table in tables:
        try:validate_table(table['result']);valid_tables.append(table)
        except (ValueError,TypeError) as error:reasons.append('Invalid calculation output: '+str(error))
    tables=valid_tables
    if contract:
        requested_kinds={s['kind'] for s in contract.get('outputs',[]) if isinstance(s,dict) and 'kind' in s}
        unrelated=[t for t in tables if t['result'].get('analysis_kind',t['tool']) not in requested_kinds]
        tables=[t for t in tables if t not in unrelated]
    # Native deterministic operations carry an explicit calculation specification.
    if contract is None and tables and all(t['result'].get('analysis_kind') in {'calendar_aggregate','monthly_revenue','correlation','comparison_summary'} for t in tables):
        contract={'outputs':[{'id':t['id'],'kind':t['result']['analysis_kind']} for t in tables]}
    if contract:
        try:
            contract=validate_requirements(contract)
            for spec in contract['outputs']:
                matched=[t['id'] for t in tables if t['id']==spec['id'] and _matches(spec,t)]
                if spec['kind']=='statistics':
                    for observation in outputs.get('observations',[]):
                        stats=observation['result'].get('statistics',{})
                        if (observation['tool']=='statistics' and stats and
                            (not spec.get('source_tables') or set(spec['source_tables'])==set(observation['source'].get('tables',[]))) and
                            (spec.get('filters') is None or spec['filters']==observation.get('parameters',{}).get('filters',[])) and
                            all(c in stats for c in spec.get('columns',[])) and
                            all(m.get('source_column') in stats and m.get('operation') in stats[m['source_column']] for m in spec.get('measures',[]))):
                            matched.append(spec['id']);completed_observations.append(observation)
                checks.append({'requirement_id':spec['id'],'status':'passed' if matched else 'missing','table_ids':matched})
                if not matched:reasons.append('Requested output was not completed: '+spec['id'])
        except ValueError as error:reasons.append(str(error))
    else:reasons.append('No validated completion contract for the requested calculation.')
    if raw.get('failed'):reasons.append('Execution stopped before the requested analysis completed.')
    if not tables and not completed_observations:reasons.append('No structured calculation output was returned. Python execution or chart capture alone does not prove completion.')
    matched_ids={ident for check in checks if check['status']=='passed' for ident in check['table_ids']}
    for table in tables:table['completion_status']='complete' if table['id'] in matched_ids else 'incomplete'
    if not reasons:tables=[table for table in tables if table['id'] in matched_ids]
    charts=outputs['charts']
    charts[:]=[c for c in charts if any(t['id']==c.get('table_id') for t in tables)]
    for table in tables:
        if can_chart(table['result']) and not any(c.get('table_id')==table['id'] for c in charts):
            charts.append({'id':'chart-'+table['id'],'kind':'result','table_id':table['id'],'specification':{}})
    artifacts=raw.get('artifacts',[])
    for artifact in artifacts:
        charts.append({'id':artifact['id'],'kind':'artifact','artifact':artifact,'table_id':None,'validation':'export_only'})
    if (contract or {}).get('chart_scope',{}).get('required') and not any(c['kind']=='result' and any(t['id']==c['table_id'] and can_chart(t['result']) for t in tables) for c in charts):
        reasons.append('The requested chart has no compatible calculated table. A generated export alone is not proof of completion.')
    status='failed' if raw.get('failed') and not tables else 'incomplete' if reasons else 'complete'
    package={'version':1,'id':package_id,'project_id':project_id,'question':question,'status':status,
             'requirements':contract,'completion_checks':checks,'incomplete_reasons':reasons,
             'tables':[{k:v for k,v in t.items() if k!='signature'} for t in tables],
             'charts':charts,'facts':[_facts(t) for t in tables]+[{'kind':'statistics','statistics':o['result']['statistics']} for o in completed_observations],
             'interpretation':[], 'provenance':raw.get('calculation') or {'steps':[]},
             'chart_scope':(contract or {}).get('chart_scope',{})}
    if len(json.dumps(package,allow_nan=False).encode())+len(json.dumps(tables[0]['result']).encode() if tables else b'')>7*1024*1024:
        package.update(status='incomplete',tables=[],charts=[],incomplete_reasons=reasons+['Result exceeds the saved analysis size limit; it was not silently truncated.'])
        tables=[];reasons=package['incomplete_reasons'];status='incomplete';raw.pop('results',None)
    json.dumps(package,allow_nan=False)
    raw['analysis_package']=package;raw['analysis_status']=status
    raw['failed']=status!='complete'
    if tables:
        raw['results']=tables[0]['result'];raw['type']='table'
        raw['content']='\n\n'.join(('### '+t['label']+'\n\n' if len(tables)>1 else '')+render_table(t['result']) for t in tables)
    else:
        raw.pop('results',None)
        if completed_observations:
            raw['content']='\n\n'.join('Calculated statistics:\n\n'+json.dumps(o['result']['statistics'],indent=2) for o in completed_observations)
    if status!='complete':raw['content']='Analysis '+status+'. '+ ' '.join(reasons)+'\n\n'+(raw['content'] if tables or status=='failed' else 'Any captured exports are incomplete outputs, not a completed answer.')
    return raw


def apply_output_contract(parameters,contract,output_id=None):
    """The planned result scope is distinct from chart scope, regardless of group names."""
    p=copy.deepcopy(parameters)
    if not contract:return p
    specs=[s for s in contract['outputs'] if s['id']==output_id] if output_id else [s for s in contract['outputs'] if s['kind']=='aggregation' and (s.get('group_by') is None or s['group_by']==p.get('group_by',[]))]
    if len(specs)!=1:return p
    spec=specs[0];scope=spec.get('scope')
    if scope:
        if scope['mode']=='all':p.pop('limit',None)
        else:p['limit']=scope['limit']
    for m in spec.get('measures',[]):
        if 'divide_by' in m:
            p.setdefault('transforms',[])
            p['transforms']=[t for t in p['transforms'] if t.get('column')!=m['source_column']]
            p['transforms'].append({'column':m['source_column'],'divide_by':m['divide_by'],'as':m.get('output',m['source_column']),'unit':m.get('unit','')})
    return p
