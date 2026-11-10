"""Typed operation registry: one vocabulary for planning, execution and evidence.

Domain checks (actual columns, date parsing, declared joins) remain mandatory in
executors. Structural validation never drops unknown fields or real predicates.
"""
import copy
import hashlib
import json
import re
from functools import lru_cache
from typing import Annotated, Any, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

AGGREGATIONS=('mean','sum','count','count_distinct','min','max')
AggregationName=Literal['mean','sum','count','count_distinct','min','max']

class ContractError(ValueError):
    def __init__(self,path,message):
        self.path=path
        super().__init__(path+': '+message)

def optional_default(factory):
    return Field(default_factory=factory,json_schema_extra={'null_as_default':True})

class Typed(BaseModel):
    @model_validator(mode='before')
    @classmethod
    def explicit_null_defaults(cls,value):
        if not isinstance(value,dict):return value
        from app.analysis.field_ownership import normalize_fields
        value=normalize_fields(cls,copy.deepcopy(value))
        for name,field in cls.model_fields.items():
            key=field.alias or name
            if value.get(key,'absent') is None and (field.json_schema_extra or {}).get('null_as_default'):
                value[key]=field.get_default(call_default_factory=True)
        return value

    @classmethod
    def __get_pydantic_json_schema__(cls,core_schema,handler):
        schema=super().__get_pydantic_json_schema__(core_schema,handler)
        for name,field in cls.model_fields.items():
            key=field.alias or name
            if (field.json_schema_extra or {}).get('null_as_default') and key in schema.get('properties',{}):
                original=schema['properties'][key]
                schema['properties'][key]={'anyOf':[original,{'type':'null'}],
                    'description':'Null has the same meaning as omission: use the declared default.'}
        return schema

    model_config=ConfigDict(extra='forbid',strict=True,allow_inf_nan=False)

class Predicate(Typed):
    column:str
    operator:Literal['==','!=','>','<','>=','<=','contains','in']
    value:Any=None
    value_column:str|None=None
    value_type:Literal['date','number','string','boolean']|None=None
    date_part:Literal['date']|None=None
    @field_validator('operator',mode='before')
    @classmethod
    def equality(cls,value):return '==' if value=='=' else value
    @model_validator(mode='after')
    def operand(self):
        reference=self.value_column is not None
        literal='value' in self.model_fields_set and (self.value is not None or not reference)
        if literal==reference:
            raise ValueError('provide exactly one of value (literal) or value_column (column reference)')
        if self.date_part and self.value_type!='date':raise ValueError('date_part requires value_type=date')
        return self

class Column(Typed):column:str
class Constant(Typed):value:float|int
class Expression(Typed):
    op:Literal['multiply','subtract','add']
    args:list[Union[Column,Constant,'Expression']]=Field(min_length=2,max_length=8)
    @model_validator(mode='after')
    def arity(self):
        if self.op=='subtract' and len(self.args)!=2:raise ValueError('subtract requires two arguments')
        return self
Expression.model_rebuild()
Formula=Union[Column,Constant,Expression]

class Transform(Typed):
    column:str
    divide_by:float|int
    as_:str=Field(alias='as')
    unit:str|None=None
    @field_validator('divide_by')
    @classmethod
    def divisor(cls,v):
        import math
        if not math.isfinite(v) or not v:raise ValueError('divide_by must be finite and nonzero')
        return v
class Derived(Typed):
    name:str
    expression:Formula
    unit:str|None=None
class AggregateMeasure(Typed):
    id:str=Field(min_length=1,pattern=r'^[A-Za-z_][A-Za-z0-9_]*$')
    column:str
    operation:AggregationName
    label:str=Field(min_length=1)
    divide_by:float|int|None=None
    unit:str|None=None
    @model_validator(mode='after')
    def conversion(self):
        import math
        if self.divide_by is not None and (not math.isfinite(self.divide_by) or self.divide_by==0):raise ValueError('divide_by must be finite and nonzero')
        return self

class Aggregation(Typed):
    measures:list[AggregateMeasure]=Field(min_length=1)
    group_by:list[str]=optional_default(list)
    filters:list[Predicate]=optional_default(list)
    derived_measures:list[Derived]=optional_default(list)
    fill_missing:dict[str,str|int|float|bool]=optional_default(dict)
    sort_by:str|None=None
    ascending:bool=True
    limit:int|None=Field(default=None,ge=1,le=100000)
    @model_validator(mode='before')
    @classmethod
    def legacy(cls,value):
        from app.analysis.aggregate_specification import from_legacy
        return from_legacy(value) if isinstance(value,dict) else value
    @model_validator(mode='after')
    def identities(self):
        ids=[m.id for m in self.measures];columns=[m.column for m in self.measures];labels=[m.label for m in self.measures]
        if len(ids)!=len(set(ids)) or len(columns)!=len(set(columns)):raise ValueError('measure identities and input columns must be unique; repeated-input operations are unsupported')
        if len(set(labels+self.group_by))!=len(labels)+len(self.group_by):raise ValueError('display labels must be unique and distinct from grouping columns')
        if set(ids)&set(self.group_by):raise ValueError('measure identities must differ from grouping columns')
        if self.sort_by and self.sort_by not in ids+self.group_by+[d.name for d in self.derived_measures]:raise ValueError('sort_by must reference a stable measure id, grouping column, or derived measure')
        if set(self.fill_missing)-set(self.group_by):raise ValueError('fill_missing must reference grouping columns')
        return self

class JoinKey(Typed):
    from_table:str
    from_column:str
    to_table:str
    to_column:str
class Source(Typed):
    tables:list[str]=Field(min_length=1)
    join_keys:list[JoinKey]=optional_default(list)
    database:str|None=None
class Metric(Typed):
    name:str
    aggregation:Literal['sum','count']
    expression:Formula|None=None
    unit:str|None=None
    @model_validator(mode='after')
    def formula(self):
        if self.aggregation=='sum' and self.expression is None:raise ValueError('sum requires an expression')
        return self
class Calendar(Typed):
    source:Source|None=None
    date_column:str
    years:list[int]=Field(min_length=1,max_length=10)
    grain:Literal['month','quarter','year']
    metric:Metric
    compare:bool=False
    filters:list[Predicate]=optional_default(list)
    output:dict[str,Any]=optional_default(lambda:{'table':True,'chart':'line'})
    @model_validator(mode='after')
    def comparison(self):
        if any(not 1678<=y<=2260 for y in self.years):raise ValueError('years must be valid calendar years')
        self.years=sorted(set(self.years))
        if self.compare and len(self.years)<2:raise ValueError('comparison requires at least two resolved years; clarify instead of using one year')
        return self
class ColumnComparison(Typed):
    column:str
    value_column:str
    operator:Literal['>','<','>=','<=','==','!=']
    value_type:Literal['date','number']|None=None
    date_part:Literal['date']|None=None
class Comparison(ColumnComparison):
    matched_label:str=Field(default='Matched',min_length=1)
    eligibility_filters:list[Predicate]=Field(default_factory=list,json_schema_extra={'input_aliases':['filters']})
    group_by:list[str]=Field(default_factory=list)
    sort_by:Literal['percentage','matched_count','comparable_count']|None=None
    ascending:bool=False
    count_label:str=Field(default='Count',min_length=1)
    comparison_label:str=Field(default='Comparison',min_length=1)
class EntityMeasurement(Typed):
    name:str=Field(min_length=1)
    expression:Formula
    aggregation:Literal['mean']='mean'
    unit:str|None=None

class EntityComparisonRule(ColumnComparison):
    operator:Literal['>','<']
    value_type:Literal['date','number']
    @model_validator(mode='after')
    def calendar_rule(self):
        if self.column==self.value_column:raise ValueError('comparison operands must differ')
        if (self.value_type=='date') != (self.date_part=='date'):
            raise ValueError('date comparisons require calendar date_part=date; numeric comparisons omit date_part')
        return self

class EntityComparison(Typed):
    population_table:str=Field(min_length=1)
    observations_table:str=Field(min_length=1)
    entity_key:str=Field(min_length=1)
    observation_key:str=Field(min_length=1)
    filters:list[Predicate]=optional_default(list)
    measurement:EntityMeasurement
    comparison:EntityComparisonRule
    matched_label:str=Field(default='Matched',min_length=1)
    unmatched_label:str=Field(default='Not matched',min_length=1)
    entity_label:str=Field(default='Entities',min_length=1)
    group_aggregation:Literal['mean']='mean'
    weighting:Literal['equal_entity']='equal_entity'
    @model_validator(mode='after')
    def bounded_grain(self):
        if self.population_table==self.observations_table:raise ValueError('population and observations must be separate declared tables')
        if self.matched_label.strip().casefold()==self.unmatched_label.strip().casefold():raise ValueError('classification labels must differ')
        labels=['Classification','Comparable '+self.entity_label,'Contributing '+self.entity_label,'Missing Measurement '+self.entity_label,self.measurement.name]
        if any(not v.strip() for v in (self.matched_label,self.unmatched_label,self.entity_label)) or len(set(labels))!=len(labels):raise ValueError('output and classification labels must be distinct and nonempty')
        return self

OperationKind=Literal['aggregation','calendar_aggregate','comparison_summary','correlation','statistics','filtering','monthly_revenue','entity_comparison']

class Correlation(Typed):
    columns:list[str]|None=None
    method:Literal['pearson','spearman']='pearson'
StatisticName=Literal['count','mean','median','min','max','std','q25','q75','iqr','outliers_count','outliers_percentage','outlier_values']
class Statistics(Typed):
    columns:list[str]=Field(min_length=1)
    statistics:list[StatisticName]=Field(min_length=1)
    return_table:bool=False
    unit:str|None=None
    @model_validator(mode='after')
    def unique(self):
        if len(set(self.columns))!=len(self.columns) or len(set(self.statistics))!=len(self.statistics):raise ValueError('statistics and columns must be distinct')
        return self
class Filtering(Typed):filters:list[Predicate]=Field(default_factory=list)
class Monthly(Typed):
    year:int=Field(ge=1678,le=2260)
    date_column:str
    unit_price_column:str
    quantity_column:str
    discount_column:str
class Visualization(Typed):
    chart_type:Literal['bar','line','scatter','histogram','box','heatmap']
    x:str
    y:str|None=None
    title:str|None=None

REGISTRY={'entity_comparison':EntityComparison,'aggregation':Aggregation,'calendar_aggregate':Calendar,'comparison_summary':Comparison,
          'correlation':Correlation,'statistics':Statistics,'filtering':Filtering,
          'monthly_revenue':Monthly,'visualization':Visualization}

def without_optional_nulls(value):
    if isinstance(value,list):return [without_optional_nulls(v) for v in value]
    if isinstance(value,dict):
        return {k:without_optional_nulls(v) for k,v in value.items()
                if (v is not None or k=='value' and not value.get('value_column'))
                and not (k=='value' and v is None and value.get('value_column'))}
    return value

def predicate_identity(value):
    p={k:copy.deepcopy(v) for k,v in value.items() if k in Predicate.model_fields}
    for key in ('value_column','value_type','date_part'):
        if p.get(key) is None:p.pop(key,None)
    if p.get('value_column') and p.get('value') is None:p.pop('value',None)
    if p.get('operator')=='=':p['operator']='=='
    return p

def validation_issue(error,raw,path):
    """Report input paths, without Pydantic union-branch class names."""
    candidates=[]
    branches={'Column','Constant','Expression'}
    for issue in error.errors(include_input=False):
        node=raw;parts=[];compatible=True;in_formula=False
        for part in issue['loc']:
            branch=part if part in branches else next((name for name in branches if isinstance(part,str) and part.startswith('function-') and re.search(r'\b'+name+r'\]+$',part)),None)
            if branch and in_formula:
                expected=('Expression' if 'op' in node else 'Column' if 'column' in node else 'Constant' if 'value' in node else None) if isinstance(node,dict) else None
                if expected and branch!=expected:compatible=False;break
                continue
            parts.append(part)
            if part in ('expression','derived'):in_formula=True
            if isinstance(node,dict):node=node.get(part)
            elif isinstance(node,list) and isinstance(part,int) and 0<=part<len(node):node=node[part]
            else:node=None
        if compatible:candidates.append((issue,parts))
    issue,parts=min(candidates,key=lambda pair:(pair[0]['type']!='extra_forbidden',len(pair[1]))) if candidates else (error.errors(include_input=False)[0],[])
    suffix=''.join(f'[{part}]' if isinstance(part,int) else '.'+part if re.fullmatch(r'[A-Za-z_]\w*',str(part)) else '['+json.dumps(str(part))+']' for part in parts)
    return ContractError(path+suffix,issue['msg'])

def validate(kind,parameters,path='$.parameters',columns=None):
    if kind not in REGISTRY:raise ContractError(path.rsplit('.',1)[0]+'.kind','unsupported operation '+repr(kind))
    p=copy.deepcopy(parameters)
    if kind=='calendar_aggregate' and isinstance(p,dict) and p.get('compare') is True and isinstance(p.get('years'),list) and len(set(p['years']))<2:
        raise ContractError(path+'.years','comparison requires at least two resolved requested years')
    if kind=='comparison_summary' and isinstance(p,dict):
        if p.get('operator')=='=':p['operator']='=='
    try:
        model=REGISTRY[kind].model_validate(p)
        # Retain explicit literal nulls; omit only absent defaults and optional null fields.
        p=without_optional_nulls(model.model_dump(by_alias=True,exclude_unset=kind!='entity_comparison'))
    except ValidationError as error:
        raise validation_issue(error,p,path) from None
    for key in ('filters','eligibility_filters'):
        if key in p:p[key]=[predicate_identity(v) for v in p[key]]
        if p.get(key)==[]:p.pop(key)
    if kind=='entity_comparison':p.setdefault('filters',[])
    if kind=='calendar_aggregate':
        p.setdefault('filters',[]);p.setdefault('compare',False);p.setdefault('output',{'table':True,'chart':'line'})
    if kind=='aggregation' and columns is not None:
        for c in [*p.get('group_by',[]),*[m['column'] for m in p['measures']]]:
            if c not in columns:raise ContractError(path+'.measures',f'unknown column {c!r}; available: {list(columns)}')
    return p


def output_contract(plan):
    """Canonical operation inputs, not a second model-written output definition."""
    from app.services.output_identity import index_outputs
    index_outputs(plan['outputs'])
    return {'outputs':[{'id':out['id'],'kind':out['kind'],'parameters':validate(out['kind'],out['parameters']),
              'source_tables':(out.get('source') or plan['source'])['tables'],
              'join_keys':(out.get('source') or plan['source']).get('join_keys',[])} for out in plan['outputs']],
            'chart_scope':copy.deepcopy(plan.get('chart_scope') or {})}


def formula_identity(node):
    if not isinstance(node,dict):return node
    if set(node)=={'value'}:
        v=node['value'];return {'value':int(v) if isinstance(v,(int,float)) and v==int(v) else v}
    if 'op' not in node:return copy.deepcopy(node)
    args=[formula_identity(arg) for arg in node['args']]
    if node['op'] in {'multiply','add'}:
        args=[child for arg in args for child in (arg['args'] if isinstance(arg,dict) and arg.get('op')==node['op'] else [arg])]
        args.sort(key=lambda arg:json.dumps(arg,sort_keys=True))
    return {'op':node['op'],'args':args}

def canonical(kind,p):
    p=validate(kind,p)
    # Defaults are semantic; omitted/empty fields have a single evidence form.
    model=REGISTRY[kind].model_validate(p)
    p=without_optional_nulls(model.model_dump(by_alias=True))
    if kind=='entity_comparison':p['measurement']['expression']=formula_identity(p['measurement']['expression'])
    if kind=='calendar_aggregate' and p.get('metric',{}).get('expression'):
        p['metric']['expression']=formula_identity(p['metric']['expression'])
    for key in ('filters','eligibility_filters'):
        if key in p:p[key]=sorted(p[key],key=lambda v:json.dumps(v,sort_keys=True))
    # Source is checked separately using resolved IDs and declared join edges.
    if kind=='calendar_aggregate':p.pop('source',None)
    return p

def covers_constraints(kind, parameters, spec):
    """Static request coverage using the same typed definitions as execution.

    This proves plan coverage only. Publication additionally requires the native
    output evidence, actual row scope, values, and ordering checks.
    """
    p=canonical(kind,parameters)
    if spec.get('group_by') is not None and spec['group_by']!=p.get('group_by',[]):return False
    if spec.get('filters') is not None:
        identity=lambda values:sorted((predicate_identity(v) for v in values),key=lambda v:json.dumps(v,sort_keys=True))
        if identity(spec['filters'])!=identity(p.get('eligibility_filters',p.get('filters',[]))):return False
    if spec.get('fill_missing') is not None and spec['fill_missing']!=p.get('fill_missing',{}):return False
    scope=spec.get('scope') or {}
    if scope.get('mode')=='all' and p.get('limit') is not None:return False
    if scope.get('mode')=='top' and scope.get('limit')!=p.get('limit'):return False
    if kind=='aggregation':
        from app.analysis.result_operations import output_definition
        definition=output_definition(p);provenance=definition['measure_provenance']
        if any(c not in definition['columns'] for c in spec.get('columns',[])):return False
        for measure in spec.get('measures',[]):
            matches=[]
            for name,origin in provenance.items():
                if any(origin.get(k)!=measure[k] for k in ('source_column','operation') if k in measure):continue
                if 'output' in measure and measure['output']!=name:continue
                if 'unit' in measure and definition['units'].get(name)!=measure['unit']:continue
                if 'divide_by' in measure and origin.get('transform',{}).get('divide_by')!=measure['divide_by']:continue
                if measure.get('derived') and formula_identity(origin.get('derived'))!=formula_identity(measure['derived']):continue
                matches.append(name)
            if not matches:return False
        if spec.get('sort_by') is not None:
            sort=definition['aliases'].get(spec['sort_by'],spec['sort_by'])
            if sort!=definition['sort_by'] or spec.get('ascending',p['ascending'])!=p['ascending']:return False
    return True

def result_digest(result):
    payload={k:result.get(k) for k in ('columns','data','row_count','units','analysis_context','measure_provenance','result_scope','source_observation_count','comparison_audit','correlation','statistics','group_populations','visualization_blueprint','entity_audit') if k in result}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,allow_nan=False).encode()).hexdigest()

def stamp(kind,p,result):
    result['operation_evidence']={'kind':kind,'parameters':canonical(kind,p),'result_sha256':result_digest(result)}
    return result

def matches(kind,p,result):
    evidence=result.get('operation_evidence') or {}
    try:
        if kind=='statistics':
            from app.analysis.statistics import verifies_selection
            if not verifies_selection(p,result):return False
        return evidence.get('kind')==kind and evidence.get('parameters')==canonical(kind,p) and evidence.get('result_sha256')==result_digest(result)
    except (ValueError,TypeError):return False

def execute(kind,p,frame):
    p=validate(kind,p)
    if kind=='entity_comparison':
        from app.analysis.entity_comparison import calculate
        return stamp(kind,p,calculate(frame,p))
    if kind=='calendar_aggregate':
        from app.analysis.calendar import calculate
        return stamp(kind,p,calculate(frame,p))
    from app.analysis_engine import AnalysisEngine
    plan={kind:p}
    if kind=='correlation':plan={'correlation':True,'correlation_columns':p.get('columns'),'correlation_method':p.get('method','pearson')}
    elif kind=='filtering':plan={'filters':p.get('filters',[])}
    return stamp(kind,p,AnalysisEngine.execute_plan(None,'prepared',plan,dataframe=frame,validate_tool_arguments=True))

class PlannedOutput(Typed):
    id:str=Field(min_length=1)
    reference_output_id:str|None=Field(default=None,exclude=True)
    kind:OperationKind
    parameters:dict[str,Any]
    source:Source|None=None
class ChartScope(Typed):
    preference:Literal['required','automatic','disabled']='automatic'
    top_n:Literal[5,10,20]=10
    @model_validator(mode='before')
    @classmethod
    def legacy(cls,value):
        if not isinstance(value,dict):return value
        value=copy.deepcopy(value)
        if 'required' in value:
            required=value.pop('required')
            if type(required) is not bool:raise ValueError('required must be boolean')
            preference='required' if required else 'automatic'
            if 'preference' in value and value['preference']!=preference:raise ValueError('conflicting chart preferences')
            value['preference']=preference
        return value

def chart_preference(scope):
    return ChartScope.model_validate(scope or {}).preference
class Presentation(Typed):
    table_in_chat:bool=False
    table_requested:bool=False

class AnalysisPlan(Typed):
    source:Source
    outputs:list[PlannedOutput]=Field(min_length=1,max_length=12)
    chart_scope:ChartScope=optional_default(ChartScope)
    presentation:Presentation=optional_default(Presentation)

class PlannerEnvelope(Typed):
    intent:Literal['SIMPLE','COMPLEX','CONVERSATION']
    context_action:Literal['standalone','inherit','clarify']='standalone'
    reference_message_id:str|None=None
    clarification:str|None=None
    unsupported_reason:str|None=None
    reasoning:str|None=None
    analysis_plan:AnalysisPlan|None=None
    # Explicit compatibility inputs; these still pass their original domain validation.
    request_requirements:dict[str,Any]|None=None
    changed_fields:list[str]=optional_default(list)

def canonical_planner_requirements(value):
    """Accept legacy duplicate descriptions at one boundary, then use typed inputs.

    Computational constraints in a redundant description must agree with the
    typed operation. Output labels and count-unit spelling are generated by the
    operation, never invented a second time by the planner. Non-parameterized
    requirements retain the strict legacy verifier for custom/older callers.
    """
    if not isinstance(value,dict) or not isinstance(value.get('outputs'),list):
        return validate_contract(value)
    specs=[]
    for i,raw in enumerate(value['outputs']):
        if not isinstance(raw,dict) or not isinstance(raw.get('parameters'),dict):
            from app.services.analysis_package import validate_requirements
            specs.extend(validate_requirements({'outputs':[raw]})['outputs']);continue
        if set(raw)-OutputRequirement.model_fields.keys():raise ContractError('$.request_requirements','unknown requirement fields')
        kind=raw['kind'];p=validate(kind,raw['parameters'],f'$.request_requirements.outputs[{i}].parameters')
        if kind=='aggregation':
            from app.analysis.aggregate_specification import kernel
            p=kernel(p)
        path=f'$.request_requirements.outputs[{i}]'
        population=p.get('eligibility_filters',p.get('filters',[]))
        if raw.get('filters') is not None:
            expected=sorted((predicate_identity(v) for v in raw['filters']),key=lambda v:json.dumps(v,sort_keys=True))
            actual=sorted(population,key=lambda v:json.dumps(v,sort_keys=True))
            if expected!=actual:raise ContractError(path+'.filters','conflicts with the typed population')
        groups=p.get('group_by',[])
        if kind=='calendar_aggregate':groups=[{'month':'Month','quarter':'Quarter','year':'Year'}[p['grain']]]
        if raw.get('group_by') is not None and raw['group_by']!=groups:raise ContractError(path+'.group_by','conflicts with typed grouping')
        if raw.get('scope'):
            scope=Scope.model_validate(raw['scope'])
            if (scope.mode=='all' and p.get('limit') is not None) or (scope.mode=='top' and scope.limit!=p.get('limit')):
                raise ContractError(path+'.scope','conflicts with typed table scope')
        if raw.get('sort_by'):
            expected=p.get('sort_by')
            if kind=='calendar_aggregate':expected=groups[0]
            if raw['sort_by']!=expected:raise ContractError(path+'.sort_by','conflicts with typed sorting')
            ascending=True if kind=='calendar_aggregate' else p.get('ascending',True)
            if raw.get('ascending') is not None and raw['ascending']!=ascending:raise ContractError(path+'.ascending','conflicts with typed sort direction')
        for j,m in enumerate(raw.get('measures') or []):
            if not isinstance(m,dict):raise ContractError(path+f'.measures[{j}]','a redundant measure must be a typed object, not a text fragment')
            op=m.get('operation');source=m.get('source_column')
            if kind=='comparison_summary':
                if m.get('derived') is not None or m.get('divide_by') is not None:raise ContractError(path+'.measures','comparison measures do not accept a different derived formula or conversion')
                allowed={'eligible_count','comparable_count','matched_count','percentage','missing_actual_count','missing_comparison_count','comparison_summary'}
                if op not in allowed:raise ContractError(path+'.measures','unsupported comparison measure')
                if source and source not in {p['column'],p['value_column']}:raise ContractError(path+'.measures.source_column','conflicts with comparison operands')
                unit=m.get('unit')
                permitted={'%','percent','percentage'} if op=='percentage' else {'count','orders','order','observations','cases',p.get('count_label','Count').lower()}
                if unit and unit.lower() not in permitted:raise ContractError(path+'.measures.unit','conflicts with the comparison measure dimension')
            elif kind=='calendar_aggregate':
                metric=p['metric']
                if op and op!=metric['aggregation']:raise ContractError(path+'.measures.operation','conflicts with typed calendar aggregation')
                if m.get('derived') and repair_formula_identity(without_optional_nulls(m['derived']))!=formula_identity(metric.get('expression')):
                    raise ContractError(path+'.measures.derived','conflicts with typed calendar formula')
                if m.get('unit')!=metric.get('unit') and m.get('unit') is not None:raise ContractError(path+'.measures.unit','conflicts with typed metric unit')
                if m.get('divide_by') is not None:raise ContractError(path+'.measures.divide_by','conversion must be present in the typed metric formula')
            elif kind=='aggregation':
                if m.get('derived'):
                    if not any(formula_identity(d['expression'])==formula_identity(m['derived']) for d in p.get('derived_measures',[])):
                        raise ContractError(path+'.measures.derived','derived measure omitted from typed aggregation')
                elif source and p['aggregations'].get(source)!={'nunique':'count_distinct'}.get(op,op):
                    raise ContractError(path+'.measures','requested aggregate is omitted or changed in typed parameters')
                transforms=[t for t in p.get('transforms',[]) if t['column']==source]
                if m.get('divide_by') is not None and not any(t['divide_by']==m['divide_by'] for t in transforms):raise ContractError(path+'.measures.divide_by','typed conversion differs')
                if m.get('unit') and not any(t.get('unit')==m['unit'] for t in transforms):raise ContractError(path+'.measures.unit','typed unit differs')
        spec={k:copy.deepcopy(raw[k]) for k in ('id','kind','source_tables','join_keys','columns') if raw.get(k) is not None}
        spec['parameters']=p;specs.append(spec)
    result={'outputs':specs}
    if value.get('chart_scope') is not None:result['chart_scope']=value['chart_scope']
    return validate_contract(result)


def validate_plan(value,history=None):
    from app.services.output_identity import resolve_outputs
    value=resolve_outputs(value,history)
    if isinstance(value,dict) and (value.get('context_action')=='clarify' or (value.get('unsupported_reason') and not value.get('analysis_plan'))):
        allowed={k:copy.deepcopy(v) for k,v in value.items() if k not in {'analysis_plan','request_requirements','completion_contract','operation','resolved_analysis'}}
        try:return PlannerEnvelope.model_validate(allowed).model_dump(exclude_unset=True)
        except ValidationError as error:raise validation_issue(error,allowed,'$') from None
    if isinstance(value,dict) and value.get('analysis_plan') and value.get('unsupported_reason'):raise ContractError('$.unsupported_reason','do not supply an executable approximation together with an unsupported request')
    if isinstance(value,dict) and value.get('analysis_plan') and value.get('intent')=='CONVERSATION':raise ContractError('$.intent','analysis_plan requires an analytical intent, not CONVERSATION')
    try:plan=PlannerEnvelope.model_validate(value).model_dump(exclude_unset=True)
    except ValidationError as error:
        e=error.errors(include_input=False)[0];path='$'+''.join(f'[{x}]' if isinstance(x,int) else '.'+str(x) for x in e['loc'])
        raise ContractError(path,e['msg']) from None
    if plan.get('analysis_plan') and plan.get('intent')!='SIMPLE':raise ContractError('$.intent','typed plans require SIMPLE intent')
    if plan.get('analysis_plan'):
        ap=plan['analysis_plan']
        for i,out in enumerate(ap['outputs']):
            out['parameters']=validate(out['kind'],out['parameters'],f'$.analysis_plan.outputs[{i}].parameters')
            if out['kind']=='calendar_aggregate':
                params=out['parameters'];nested=params.pop('source',None);owner=out.get('source') or ap['source']
                if nested:
                    from app.services.planned_analysis import join_identity
                    if set(nested['tables'])!=set(owner['tables']) or join_identity(nested.get('join_keys',[]))!=join_identity(owner.get('join_keys',[])):
                        raise ContractError(f'$.analysis_plan.outputs[{i}].parameters.source','conflicts with the operation source')
                params.pop('output',None)  # Presentation is owned by chart_scope and metric.name.

        from app.analysis.entity_comparison import resolve_plan_sources
        resolve_plan_sources(ap)
        from app.services.change_paths import permissions
        # Schema ownership first; baseline-dependent bounds and unchanged fields
        # are checked inside QueryPlanner's existing validation/repair attempt.
        plan['changed_fields']=permissions(ap,plan.get('changed_fields',[]),check_indices=False)

    if plan.get('request_requirements'):
        from app.services.analysis_package import validate_requirements
        plan['request_requirements']=canonical_planner_requirements(plan['request_requirements'])
        if plan.get('analysis_plan'):
            # Legacy duplicate declarations must agree computationally. They do
            # not become new independently grounded request constraints.
            from app.services.request_requirements import validate_plan_request
            try:validate_plan_request(plan,plan['request_requirements'])
            except ValueError as error:raise ContractError('$.request_requirements',str(error)) from None
            plan.pop('request_requirements')
    return plan

SECRET=re.compile(r'sk-(?:or-v1-)?[A-Za-z0-9_-]{16,}|Bearer\s+\S+',re.I)
def sanitize(value):
    if isinstance(value,dict):return {str(k):('[REDACTED]' if re.sub(r'[_-]','',str(k)).lower() in {'key','apikey','openrouterapikey','token','accesstoken','refreshtoken','secret','password','authorization'} else sanitize(v)) for k,v in value.items()}
    if isinstance(value,list):return [sanitize(v) for v in value[:100]]
    if isinstance(value,str):return SECRET.sub('[REDACTED]',value)[:16000]
    return value

@lru_cache(maxsize=1)
def planner_instructions():
    schemas={name:model.model_json_schema() for name,model in REGISTRY.items() if name!='visualization'}
    envelope=PlannerEnvelope.model_json_schema()
    for key in ('request_requirements',):
        envelope['properties'].pop(key,None)
    custom_contract=CompletionContract.model_json_schema()
    envelope['$defs'].update(custom_contract.pop('$defs',{}))
    envelope['properties']['request_requirements']={**custom_contract,'description':'Custom Python only: independently useful requested outputs. Never duplicate a deterministic analysis_plan.'}
    envelope['allOf']=[{'if':{'properties':{'intent':{'const':'SIMPLE'}}},'then':{'properties':{'request_requirements':{'type':'null'}}}}]
    envelope['required']=['intent','context_action']
    # Couple each discriminator to its parameter schema in the planner contract.
    output_properties=copy.deepcopy(envelope['$defs']['PlannedOutput']['properties'])
    choices=[]
    for name,schema in schemas.items():
        schema=copy.deepcopy(schema)
        if name=='calendar_aggregate':
            schema['properties'].pop('source',None);schema['properties'].pop('output',None)
        envelope['$defs'].update(schema.pop('$defs',{}))
        ref='Parameters_'+name;envelope['$defs'][ref]=schema
        choices.append({'type':'object','additionalProperties':False,'required':['kind','parameters'],
                        'properties':{**output_properties,'kind':{'const':name},'parameters':{'$ref':'#/$defs/'+ref}}})
    envelope['$defs']['PlannedOutput']={'oneOf':choices}
    from app.services.change_paths import instructions as change_path_instructions
    return change_path_instructions()+'\n'+'''You plan analyses for an offline data analyst. Return JSON only.
Use intent SIMPLE for supported registry operations, COMPLEX only for custom Python, CONVERSATION for non-calculation discussion.
Always explicitly decide context_action: standalone, inherit, or clarify. Explicit named sources/metrics override unrelated history. A demonstrative word alone does not make a request a follow-up.
Return one complete analysis_plan for SIMPLE requests. COMPLEX custom Python requests may declare request_requirements for verification of their requested outputs; they must not provide a deterministic plan. SIMPLE requests must not return request_requirements, resolved_analysis, resolved_query, operation, or completion_contract. You alone resolve language into the specification. Verification proves execution of that specification, not independent understanding of English. Preserve uncertain intent as clarification or unsupported, never a reduced approximation. Optional nulls are accepted only where the schema explicitly gives null the default meaning.
For supported analyses return analysis_plan with source and outputs; each output has id, kind and parameters. These SAME typed parameters execute and prove completion. Do not separately invent completion_contract or resolved_analysis when using analysis_plan.
Use exact catalog table IDs and declared join keys. Each output may override source for separate populations. Do not join different SQLite databases; return unsupported_reason explaining that constraint with no invented mapping/count.
Calendar operations use date_column, years (ALL requested/reference years), grain, compare, filters, and metric {name,aggregation,expression,unit?}. Expressions have column/value leaves or op multiply/subtract/add with args. compare:true needs at least two years. Restore latest successful comparison after reload; failed turns are not successful comparisons. If referenced years cannot be resolved, clarify.
Aggregation parameters: measures [{id,column,operation,label,divide_by?,unit?}], group_by, fill_missing, derived_measures, filters, sort_by, ascending, limit. A measure id is stable, column is an actual input column, operation is the supported aggregate, and label is display text. sort_by references a measure id or grouping column. These roles are distinct; never invent internal aggregate column names. count_distinct is a real distinct count; never substitute count. An actual top-N table uses limit and sort_by. An ALL-groups table has NO limit even if chart_scope.top_n is 10. Convert cents with divide_by:100 and unit:"BRL" on that measure, not prose. Missing categorical values use fill_missing. Multiple metrics/populations can be separate outputs.
Statistics parameters require columns and an explicit statistics selection (count means nonmissing count; mean, median, min, max, std, q25, q75, iqr, outliers_count, outliers_percentage, outlier_values). Return only selected statistics. Use unit to retain the requested measurement units. Select outlier_values only when the actual values are requested. chart_scope.preference is required, automatic, or disabled. Explicit no-chart requests use disabled; this does not disable tables.
comparison_summary supports group_by (including joined customer_state), eligibility_filters, column/operator/value_column, value_type/date_part, matched_label, count_label (e.g. Orders), comparison_label (e.g. Estimated), sort_by (percentage, matched_count, comparable_count), ascending. It returns ONE combined table with comparable denominator, matched numerator, percentage and missing-date counts per group, retaining zero matches and null percentages for zero denominators. Use sort_by:percentage,ascending:false for percentage rankings; nulls are last. It always returns all groups; chart Top N is separate. Missing comparison counts are among rows with an actual value. Do not split a grouped comparison into separate count aggregations or substitute count sorting for percentage sorting. Never omit a requested measure, population, grouping, formula or order because a smaller plan is easier to execute. Return unsupported_reason or clarify if the complete request cannot be represented.
entity_comparison supports a bounded mean-of-entity-means comparison: source.tables contains exactly population_table and observations_table, with one declared single-column foreign key observations.observation_key -> population.entity_key. Parameters: population_table, observations_table, entity_key, observation_key, filters (population predicates), measurement {name,expression,aggregation:"mean",unit?}, comparison {column,value_column,operator:">" or "<",value_type:"date" or "number",date_part:"date" for dates}, matched_label, unmatched_label, entity_label, group_aggregation:"mean", weighting:"equal_entity". First average usable measurements within each entity, LEFT JOIN those means to unique population entities, classify comparable entities, then average the per-entity means equally in each class. Equality is unmatched. Missing dates and missing observations are audited separately. Never join raw repeated observations before aggregation, substitute a row-weighted average, or split the calculation into unrelated count/mean outputs. Only the mean -> comparison -> equal-entity mean composition is supported; other compositions must clarify or remain unsupported.
Calendar output must retain grouping, all years, exact formula, eligibility filters and units. State currency units only when known. Column date comparisons use value_column, value_type:date,date_part:date, never a literal column name in value.
For follow-ups, reference_message_id selects the successful specification. Each output should use reference_output_id copied from that specification, omitting id; the system retains the stored identity. Standalone outputs may omit id for system allocation. Never derive identity from a year, label, grouping or list position. Provide the fully resolved analysis_plan, and changed_fields paths such as outputs.primary.parameters.years or outputs.review_comparison.parameters.filters.1.value. Preserve all fields outside those paths. Use source, chart_scope or presentation for explicit source/presentation changes. presentation.table_in_chat controls explicit requests to print a table in chat; presentation.table_requested preserves an explicitly requested table in Open result even for scalar answers. Missing or ambiguous references must clarify. Standalone specifications never inherit fields. Do not refer to earlier failed calculations as successes. On schema repair preserve the requested meaning; correct only the invalid representation.
Envelope schema:
'''+json.dumps(envelope)

class Scope(Typed):
    mode:Literal['all','top']='all'
    limit:int|None=Field(default=None,ge=1,le=100000)
    @model_validator(mode='after')
    def ranking(self):
        if self.mode=='top' and self.limit is None:raise ValueError('top scope requires limit')
        if self.mode=='all' and self.limit is not None:raise ValueError('all scope cannot impose a table limit')
        return self
class MeasureRequirement(Typed):
    source_column:str|None=None
    operation:str|None=None
    output:str|None=None
    unit:str|None=None
    derived:Formula|None=None
    divide_by:float|int|None=None
class ComparisonMeasureRequirement(Typed):
    operation:Literal['eligible_count','comparable_count','matched_count','percentage','missing_actual_count','missing_comparison_count']
    output:str|None=Field(default=None,description='One exact result column name, never prose or a list of metrics. Omit when operation identifies the measure.')
    source_column:str|None=None
    unit:str|None=None

class OutputRequirement(Typed):
    id:str=Field(min_length=1)
    kind:OperationKind
    parameters:dict[str,Any]|None=None
    columns:list[str]|None=Field(default=None,description="Required RESULT column names, not raw input columns. Omit or use null if typed parameters fully specify the output.")
    source_tables:list[str]|None=None
    join_keys:list[JoinKey]|None=None
    group_by:list[str]|None=None
    filters:list[Predicate]|None=None
    measures:list[MeasureRequirement]|None=None
    scope:Scope|None=None
    fill_missing:dict[str,str|int|float|bool]|None=None
    sort_by:str|None=None
    ascending:bool|None=None
class CompletionContract(Typed):
    outputs:list[OutputRequirement]=Field(min_length=1)
    chart_scope:ChartScope|None=None

def _contract_payload(value):
    """Normalize nullable schema fields, preserving data-level null literals.

    Omitted and null optional requirement fields mean no additional constraint.
    Walk model fields, not arbitrary dictionary keys: parameters and predicate
    literals may contain meaningful null values. Required fields and incorrect
    types have already been rejected by Pydantic, before normalization.
    """
    if isinstance(value,BaseModel):
        payload={}
        for name,field in type(value).model_fields.items():
            if name not in value.model_fields_set:continue
            child=getattr(value,name)
            literal_null=isinstance(value,Predicate) and name=='value' and value.value_column is None
            if child is None and field.default is None and not literal_null:continue
            payload[field.serialization_alias or field.alias or name]=_contract_payload(child)
        return payload
    if isinstance(value,list):return [_contract_payload(v) for v in value]
    if isinstance(value,dict):return {k:_contract_payload(v) for k,v in value.items()}
    return value


def validate_contract(value):
    try:model=CompletionContract.model_validate(value)
    except ValidationError as error:
        e=error.errors(include_input=False)[0]
        suffix=''.join(f'[{x}]' if isinstance(x,int) else '.'+str(x) for x in e['loc'])
        raise ContractError('$.completion_contract'+suffix,e['msg']) from None
    result=_contract_payload(model)
    for i,spec in enumerate(result['outputs']):
        if spec['kind']=='comparison_summary':
            expanded=[]
            for j,measure in enumerate(spec.get('measures',[])):
                if measure.get('operation')==spec['kind']:
                    # Compatibility: an operation-wide descriptor describes the
                    # whole output, not a column. Expand it to EVERY native
                    # measure; do not discard it or relax any other requirement.
                    # Per-column constraints belong to atomic measures/columns.
                    if any(k not in {'operation','output'} for k in measure) or not spec.get('parameters'):
                        raise ContractError(f'$.outputs[{i}].measures[{j}]',
                            'An operation-wide comparison descriptor requires typed parameters and cannot override source, formula, units or transformations.')
                    from app.analysis.comparison_summary import measure_requirements
                    parameters=validate('comparison_summary',spec['parameters'])
                    expanded.extend(measure_requirements(parameters))
                    continue
                try:ComparisonMeasureRequirement.model_validate(measure)
                except ValidationError as error:
                    issue=error.errors(include_input=False)[0]
                    suffix=''.join('.'+str(k) for k in issue['loc'])
                    raise ContractError(f'$.outputs[{i}].measures[{j}]'+suffix,
                        'A comparison measure must identify ONE measure (eligible_count, comparable_count, matched_count, percentage, missing_actual_count, missing_comparison_count); output is one exact result column. If typed comparison parameters already specify all requested measures, omit redundant measures. '+issue['msg']) from None
                expanded.append(measure)
            if 'measures' in spec:spec['measures']=expanded
        if spec.get('scope') is not None:spec['scope'].setdefault('mode','all')
        for measure in spec.get('measures') or []:
            if measure.get('operation')=='nunique':measure['operation']='count_distinct'
    return result

def repair_formula_identity(node):
    """Recognize typed-node wrappers only for meaning-preserving schema repair.

    Execution still accepts only the strict Formula schema. A model sometimes
    adds the schema branch name around a valid node (e.g. Constant). Removing
    that wrapper must preserve the complete expression and every leaf value.
    Unknown wrappers remain opaque and cannot be removed by this guard.
    """
    if not isinstance(node,dict):return node
    branch_models={model.__name__.lower():model for model in (Column,Constant,Expression)}
    if len(node)==1:
        name,child=next(iter(node.items()))
        model=branch_models.get(name.lower())
        if model and isinstance(child,dict):
            try:model.model_validate(child)
            except ValidationError:pass
            else:return repair_formula_identity(child)
    if 'op' in node and isinstance(node.get('args'),list):
        return formula_identity({**node,'args':[repair_formula_identity(arg) for arg in node['args']]})
    return formula_identity(node)

def repair_representation(value):
    """Materialize inherited sources before comparing repaired JSON paths."""
    result=copy.deepcopy(value)
    if not isinstance(result,dict):return result
    plan=result.get('analysis_plan')
    if not isinstance(plan,dict) or not isinstance(plan.get('source'),dict):return result
    for out in plan.get('outputs',[]):
        if not isinstance(out,dict):continue
        if out.get('source') is None:out['source']=copy.deepcopy(plan['source'])
        p=out.get('parameters')
        if out.get('kind')=='calendar_aggregate' and isinstance(p,dict) and p.get('source') is None:
            p['source']=copy.deepcopy(out['source'])
    return result

def repair_invariants(value):
    """Keep valid semantic atoms from a rejected representation across schema repair."""
    atoms={}
    def walk(node,path=''):
        if isinstance(node,dict):
            if {'column','operator'} <= node.keys():
                atoms[path]=json.dumps(predicate_identity(node),sort_keys=True)
            if {'op','args'} <= node.keys():
                atoms[path]=json.dumps(repair_formula_identity(node),sort_keys=True)
            for key,val in node.items():
                if key in {'chart_scope','output','scope','result_scope'} and val is not None:
                    normalized=ChartScope.model_validate(val).model_dump() if key=='chart_scope' else without_optional_nulls(val)
                    atoms[path+'.'+key]=json.dumps(normalized,sort_keys=True)
                elif key in {'years','grain','date_column','compare','divide_by','unit','source_tables','tables','limit','join_keys','group_by','sort_by','ascending','population_table','observations_table','entity_key','observation_key','weighting','group_aggregation','aggregation','id','column','operation','label'}:
                    if val is not None:atoms[path+'.'+key]=json.dumps(val,sort_keys=True)
                elif key=='aggregations' and isinstance(val,dict):
                    for col,op in val.items():
                        if isinstance(op,str):atoms[path+'.aggregations.'+col]={'nunique':'count_distinct','avg':'mean'}.get(op,op)
                elif key in {'filters','eligibility_filters'} and isinstance(val,list):
                    for i,predicate in enumerate(val):
                        if isinstance(predicate,dict):
                            for field,v in predicate_identity(predicate).items():atoms[path+'.'+key+f'[{i}].'+field]=json.dumps(v,sort_keys=True)
                elif key in {'expression','derived'} and isinstance(val,dict):atoms[path+'.'+key]=json.dumps(repair_formula_identity(val),sort_keys=True)
                walk(val,path+'.'+key)
        elif isinstance(node,list):
            for i,val in enumerate(node):walk(val,path+f'[{i}]')
    walk(value)
    return atoms

def guard_repair(original,repaired,invalid_path=None,history=None):
    from app.services.output_identity import resolve_outputs
    original=resolve_outputs(original,history)
    repaired=resolve_outputs(repaired,history)
    if invalid_path and invalid_path.startswith('$.changed_fields'):
        original=copy.deepcopy(original)
        original['changed_fields']=copy.deepcopy(repaired.get('changed_fields',[]))
    raw_repaired=copy.deepcopy(repaired)
    repaired=validate_plan(repaired)
    if isinstance(original,dict) and original.get('analysis_plan'):
        if not repaired.get('analysis_plan'):
            raise ContractError('$.analysis_plan','schema repair cannot remove the requested calculation')
        from app.analysis.repair_semantics import compare_typed_repair
        original,compared=compare_typed_repair(original,raw_repaired)
        if compared:return
    original=repair_representation(original);repaired=repair_representation(raw_repaired)
    before=repair_invariants(original);after=repair_invariants(repaired)
    def measures(node):
        found=set()
        if isinstance(node,dict):
            metric=node.get('metric')
            if isinstance(metric,dict) and isinstance(metric.get('aggregation'),str):
                found.add(('calendar:'+json.dumps(repair_formula_identity(metric.get('expression')),sort_keys=True),metric['aggregation']))
            if isinstance(node.get('aggregations'),dict):
                found.update((c,{'nunique':'count_distinct','avg':'mean'}.get(op,op)) for c,op in node['aggregations'].items() if isinstance(op,str))
            if node.get('source_column') and node.get('operation') and not node.get('derived'):
                found.add((node['source_column'],{'nunique':'count_distinct'}.get(node['operation'],node['operation'])))
            for value in node.values():found.update(measures(value))
        elif isinstance(node,list):
            for value in node:found.update(measures(value))
        return found
    def facts(node):
        result=set()
        if isinstance(node,dict):
            for key,value in node.items():
                if key in {'unit','divide_by'} and value is not None:result.add((key,str(value)))
                if key in {'tables','source_tables'} and isinstance(value,list):
                    result.update(('source',x) for x in value if isinstance(x,str) and '::' in x)
                if key in {'filters','eligibility_filters'} and isinstance(value,list):
                    for predicate in value:
                        if isinstance(predicate,dict):
                            identity=predicate_identity(predicate)
                            try:Predicate.model_validate(identity)
                            except ValidationError:continue
                            result.add(('predicate',json.dumps(identity,sort_keys=True)))
                if key in {'expression','derived'} and isinstance(value,dict) and ('op' in value or 'column' in value):
                    result.add(('formula',json.dumps(repair_formula_identity(value),sort_keys=True)))
                result.update(facts(value))
        elif isinstance(node,list):
            for value in node:result.update(facts(value))
        return result
    removed=facts(original)-facts(repaired)
    if removed:raise ContractError('$','schema repair changed source, population predicates, formula, units or transformations; clarify instead')
    missing=measures(original)-measures(repaired)
    if missing:raise ContractError('$','schema repair changed requested measure identities '+repr(sorted(missing)))
    # A repair can move a legacy representation into analysis_plan; complete typed
    # evidence still validates there. Within the same representation atoms cannot drift.
    for path,value in before.items():
        same_representation=('analysis_plan' in original)==('analysis_plan' in repaired) if isinstance(original,dict) and isinstance(repaired,dict) else True
        if (path in after and after[path]!=value) or (same_representation and path not in after):
            raise ContractError('$'+path,'schema repair changed a requested calculation field; clarify instead')
