"""Bounded, project-scoped successful analysis history; never load raw result rows."""
import ast
import json
import copy
import re
from sqlalchemy import func,case
from app.models.chat import DBChatHistory


def code_facts(code):
    facts={'expressions':[], 'years':[], 'date_columns':[], 'periods':[]}
    try: tree=ast.parse(code)
    except SyntaxError:return facts
    for node in ast.walk(tree):
        if isinstance(node,ast.Assign) and isinstance(node.value,ast.BinOp):
            expression=ast.unparse(node.value)
            if len(expression)<500: facts['expressions'].append(expression)
        if isinstance(node,ast.Compare):
            for value in node.comparators:
                if isinstance(value,ast.Constant) and isinstance(value.value,int) and 1678<=value.value<=2260:
                    facts['years'].append(value.value)
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.args:
            if node.func.attr=='to_datetime' and isinstance(node.args[0],ast.Subscript):
                key=node.args[0].slice
                if isinstance(key,ast.Constant):facts['date_columns'].append(key.value)
            if node.func.attr=='to_period' and isinstance(node.args[0],ast.Constant):facts['periods'].append(node.args[0].value)
    return facts


def load_context(db, project_id):
    valid=func.json_valid(DBChatHistory.metadata_json)==1
    safe=case((valid,DBChatHistory.metadata_json),else_='{}')
    def field(path):return func.json_extract(safe,path)
    rows=db.query(DBChatHistory.id,func.substr(field('$.question'),1,1000),
                  func.substr(func.coalesce(field('$.analysis_context'),field('$.results.analysis_context')),1,16000),
                  func.substr(field('$.calculation'),1,16000),field('$.analysis_failed')).filter(
        DBChatHistory.project_id==project_id,DBChatHistory.role=='assistant',valid,
        func.coalesce(field('$.analysis_failed'),0)==0,
        field('$.calculation.steps[#-1].status')=='succeeded'
    ).order_by(DBChatHistory.created_at.desc(),DBChatHistory.id.desc()).limit(20).all()
    history=[]
    for ident,question,context,calculation,failed in rows:
        if failed:continue
        try:
            steps=json.loads(calculation or '{}').get('steps',[])
            if not steps or steps[-1].get('status')!='succeeded':continue
            state=json.loads(context) if context else None
            # Legacy result-native state is authoritative for old calendar rows.
            if not (isinstance(state,dict) and state.get('version')==1):
                native=db.query(func.json_extract(DBChatHistory.metadata_json,'$.results.analysis_context')).filter(DBChatHistory.id==ident).scalar()
                if native:state=json.loads(native)
            state=_historical_context(state,steps)
            step=steps[-1]
            source=state['plan']['source'] if state else None
            source=source or {'tables':step.get('tables',[]),'join_keys':step.get('join_keys',[])}
            entry={'message_id':ident,'question':question,'source':source,'analysis':state}
            if not state:
                entry['tool']=step.get('tool')
                params=step.get('parameters',{})
                entry['parameters']={k:v for k,v in params.items() if k!='code'}
                if params.get('code'):entry['code_facts']=code_facts(params['code'])
            history.append(entry)
            if len(history)==3:break
        except (ValueError,TypeError):continue
    result={'recent_successes':history}
    latest=db.query(DBChatHistory).filter(DBChatHistory.project_id==project_id,DBChatHistory.role=='assistant').order_by(DBChatHistory.created_at.desc(),DBChatHistory.id.desc()).first()
    if latest:
        try:
            meta=json.loads(latest.metadata_json or '{}');request=meta.get('requested_analysis') or {}
            if meta.get('unresolved_intent'):
                result['unresolved_request']={'message_id':latest.id,'succeeded':False,**meta['unresolved_intent']}
            elif meta.get('analysis_failed') and request:
                states=[o['parameters'] for o in request.get('outputs',[]) if o.get('kind')=='calendar_aggregate']
                state=states[0] if len(states)==1 else request if request.get('date_column') else None
                result['unresolved_request']={'message_id':latest.id,'question':meta.get('question'),'succeeded':False,'state':state}
        except (ValueError,TypeError):pass
    return result


def from_result(result):
    package=result.get('analysis_package') or {}
    if package.get('status')!='complete' or not result.get('analysis_plan'):return None
    from app.analysis.operations import validate_plan
    plan=validate_plan({'intent':'SIMPLE','analysis_plan':result['analysis_plan']})['analysis_plan']
    return {'version':1,'plan':copy.deepcopy(plan)}


def _historical_context(state, steps):
    """Read-only adapter for records written before the canonical envelope."""
    if isinstance(state,dict) and state.get('version')==1 and state.get('plan'):
        state=copy.deepcopy(state)
        from app.services.output_identity import index_outputs
        index_outputs(state['plan']['outputs'])
        from app.analysis.operations import validate
        for out in state['plan'].get('outputs',[]):
            if out.get('kind')=='statistics' and 'statistics' not in out['parameters']:
                from app.analysis.statistics import LEGACY_STATISTICS
                out['parameters']={**out['parameters'],'statistics':list(LEGACY_STATISTICS)}
            if out.get('kind')=='aggregation':out['parameters']=validate('aggregation',out['parameters'])
        return state
    if isinstance(state,dict) and state.get('metric') and state.get('date_column'):
        params=copy.deepcopy(state);source=params.pop('source',None)
        if source:return {'version':1,'plan':{'source':source,'outputs':[{'id':'primary','kind':'calendar_aggregate','parameters':params}]}}
    step=steps[-1] if steps else {}
    if state and state.get('tool') and state['tool']!='run_code':
        items=state.get('outputs') or [state]
        if len(items)>1 and any(not o.get('id') for o in items):return None
        outputs=[{'id':o.get('id','primary'),'kind':o['tool'],'parameters':o.get('parameters',{}),
                  'source':o.get('source') or state.get('source')} for i,o in enumerate(items)]
        return {'version':1,'plan':{'source':state.get('source') or {'tables':step.get('tables',[]),'join_keys':step.get('join_keys',[])},'outputs':outputs}}
    if step.get('tool')=='monthly_revenue':
        # Existing saved monthly results retain their original arithmetic/schema.
        return {'version':1,'plan':{'source':{'tables':step.get('tables',[]),'join_keys':step.get('join_keys',[])},
                'outputs':[{'id':'primary','kind':'monthly_revenue','parameters':step.get('parameters',{})}]}}
    return None
