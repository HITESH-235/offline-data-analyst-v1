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
                  func.substr(func.coalesce(field('$.results.analysis_context'),field('$.analysis_context')),1,16000),
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
            step=steps[-1]
            source=state.get('source') if state else None
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
    return {'recent_successes':history}


def grouping_update(question, history):
    """Resolve a reference-only calendar grouping edit without rewriting its scope."""
    if re.search(r'\d', question):return None
    words=re.findall(r'[a-z]+', question.lower())
    grains={'monthly':'month','month':'month','months':'month','quarterly':'quarter','quarter':'quarter',
            'quarters':'quarter','annually':'year','annual':'year','yearly':'year','year':'year','years':'year'}
    allowed={'now','please','show','display','present','plot','group','regroup','break','down','by','per','instead',
             'it','that','this','those','these','them','the','same','as','a','on','basis','can','could','you','we','see','make'}
    requested={grains[word] for word in words if word in grains}
    if (len(requested)!=1 or not set(words)&{'it','that','this','those','these','them','same'}
            or any(word not in allowed and word not in grains for word in words)):
        return None
    successes=history.get('recent_successes',[])
    if not successes:return {'intent':'SIMPLE','context_action':'clarify','clarification':'Which analysis should I regroup? Please specify its metric and years.'}
    latest=successes[0];state=latest.get('analysis') or {}
    if not all(key in state for key in ('source','metric','date_column','years','grain')):
        return None  # Legacy records still need semantic reconstruction from bounded facts.
    return {'intent':'SIMPLE','context_action':'inherit','reference_message_id':latest['message_id'],
            'resolved_analysis':{'grain':requested.pop()},'resolution_kind':'grouping_update'}


CONTEXT_INSTRUCTIONS='''
You also resolve analysis references BEFORE table selection and execution.
The bounded successful-analysis history below is project-local. Failed turns and generic advice do not replace a successful analysis.
Return context_action: "standalone", "inherit", or "clarify". Inherit only when the current question refers to previous analysis (pronouns, continuation, changing its grouping or comparison). Standalone explicit questions MUST NOT inherit old filters or metrics.
When inheriting, provide reference_message_id from recent_successes for the relevant successful analysis. Use the latest relevant success; if more than one could be intended, clarify instead of choosing silently.
If the reference or an explicit source/metric change is ambiguous, return context_action:"clarify" and a concise clarification question; do not guess.
For calendar sums/counts, include resolved_analysis with this JSON structure:
{"source":{"tables":["database.db::Table"],"join_keys":[]},"metric":{"name":"Revenue","aggregation":"sum","expression":{"op":"multiply","args":[{"column":"UnitPrice"},{"column":"Quantity"},{"op":"subtract","args":[{"value":1},{"column":"Discount"}]}]}},"date_column":"OrderDate","years":[2021],"grain":"month","compare":false,"filters":[],"output":{"table":true,"chart":"line"}}
This is an expression schema, NOT a Northwind-only template: select actual columns/formula for the requested metric. Supported expression operators: multiply, subtract, add; leaves column or finite numeric value. Count uses aggregation:"count" and no expression. Sum Freight uses expression:{"column":"Freight"}.
Allowed grains: month, quarter, year. For comparison use all requested years including the referenced base year; compare:true aligns periods across years. Preserve all unrelated predicates, metric/formula, date column, canonical source table IDs, and declared join keys. Replace only what the user explicitly changes. years encodes calendar-year filtering; do not duplicate obsolete date filters in filters. Include relevant non-date filters as validated predicates.
Use prior structured analysis when present, otherwise reconstruct from its verified successful tool parameters/code facts and question. Never use narrative preview rows to establish calculations. If reconstruction is uncertain, clarify.
A follow-up calendar request MUST execute an analysis, not be classified as CONVERSATION. Return intent:SIMPLE with resolved_analysis for supported calendar calculations. Other follow-ups should include resolved_query, a complete standalone analytical question retaining prior formula, source, filters and grouping, for the existing agent tools.
'''


def from_result(result):
    package=result.get('analysis_package')
    if package and package.get('status')!='complete':return None
    if package and package.get('tables'):
        tables=package['tables'];primary=tables[0]
        native=primary['result'].get('analysis_context')
        if native:return copy.deepcopy(native)
        if primary['result'].get('analysis_kind')!='monthly_revenue':
            return {'source':copy.deepcopy(primary['source']),'tool':primary['tool'],
                    'parameters':copy.deepcopy(primary['parameters']),
                    'outputs':[{'id':t['id'],'source':copy.deepcopy(t['source']),'tool':t['tool'],
                                'parameters':copy.deepcopy(t['parameters']),
                                'columns':t['result']['columns'],'units':t['result'].get('units',{})} for t in tables]}
    resolved=(result.get('results') or {}).get('analysis_context') or result.get('analysis_context')
    if resolved:return copy.deepcopy(resolved)
    data=result.get('results') or {};steps=(result.get('calculation') or {}).get('steps',[])
    if not steps or steps[-1].get('status')!='succeeded':return None
    step=steps[-1];source={'tables':step.get('tables',[]),'join_keys':step.get('join_keys',[])}
    if data.get('analysis_kind')=='monthly_revenue':
        p=step.get('parameters',{});year=data['verification']['year']
        return {'source':source,'metric':{'name':'Revenue','aggregation':'sum','expression':{'op':'multiply','args':[
            {'op':'multiply','args':[{'column':p.get('unit_price_column','UnitPrice')},{'column':p.get('quantity_column','Quantity')}]},
            {'op':'subtract','args':[{'value':1},{'column':p.get('discount_column','Discount')}]}]}},
            'date_column':p.get('date_column','OrderDate'),'years':[year],'grain':'month','compare':False,'filters':[],
            'output':{'table':True,'chart':'line'}}
    context={'source':source,'tool':step.get('tool'),'parameters':{k:v for k,v in step.get('parameters',{}).items() if k!='code'}}
    if step.get('tool')=='run_code':context['code_facts']=code_facts(step.get('parameters',{}).get('code',''))
    return context
