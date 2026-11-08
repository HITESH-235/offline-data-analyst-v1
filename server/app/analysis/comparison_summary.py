"""One validated comparison calculation, with explicit population/coverage counts."""
from app.analysis.filtering import filter_data,parse_dates,column_comparison
import copy
import json

PARAMETER_SCHEMA={
 'type':'object','additionalProperties':False,'required':['column','value_column','operator'],
 'properties':{'column':{'type':'string'},'value_column':{'type':'string'},
  'operator':{'enum':['>','<','>=','<=','==','!=']},'value_type':{'enum':['date','number']},
  'date_part':{'enum':['date']},'matched_label':{'type':'string','minLength':1},
  'eligibility_filters':{'type':'array','minItems':1,'items':{'type':'object','additionalProperties':False,
   'required':['column','operator','value'],'properties':{'column':{'type':'string'},
    'operator':{'enum':['>','<','>=','<=','==','!=','contains','in']},'value':{},
    'value_type':{'enum':['date','number','string','boolean']}}}}}}
EXAMPLE_PARAMETERS={'column':'order_delivered_customer_date','value_column':'order_estimated_delivery_date',
 'operator':'>','value_type':'date','date_part':'date','matched_label':'Late',
 'eligibility_filters':[{'column':'order_status','operator':'==','value':'delivered'}]}


def contract_instructions():
 return ('comparison_summary canonical argument contract: '+json.dumps(PARAMETER_SCHEMA)
         +'\nValid example: '+json.dumps(EXAMPLE_PARAMETERS)
         +'\nUse eligibility_filters for the population; column/operator/value_column define the event. '
         'Calendar dates use value_type=date and date_part=date. matched_label names the numerator. '
         'Compatibility aliases are explicit: filters becomes eligibility_filters, and = becomes ==. '
         'Never supply both population fields or unknown fields. Do not remove population filters to fix a schema error. '
         'The operation reports missing actual/comparison dates and excludes missing comparisons from the percentage denominator.')


def normalize_parameters(p):
 if not isinstance(p,dict):raise ValueError(contract_instructions())
 allowed=set(PARAMETER_SCHEMA['properties'])|{'filters'}
 if set(p)-allowed or not set(PARAMETER_SCHEMA['required'])<=set(p):
  raise ValueError('Invalid comparison_summary fields: '+str(sorted(set(p)-allowed))+'. '+contract_instructions())
 if 'filters' in p and 'eligibility_filters' in p:
  raise ValueError('Supply eligibility_filters OR legacy filters, not both; the population would be ambiguous.')
 result=copy.deepcopy(p)
 if 'filters' in result:result['eligibility_filters']=result.pop('filters')
 filters=result.get('eligibility_filters')
 if filters is not None:
  if not isinstance(filters,list) or not filters:raise ValueError('eligibility_filters must be a nonempty list of validated predicates; omit it for the full population.')
  for item in filters:
   if not isinstance(item,dict):raise ValueError('Each eligibility filter must be an object.')
   if 'value_column' in item and {item.get('column'),item.get('value_column')}=={p['column'],p['value_column']}:
    raise ValueError('Do not filter the population by the event comparison: that corrupts the denominator.')
   shape=PARAMETER_SCHEMA['properties']['eligibility_filters']['items']
   if set(item)-set(shape['properties']) or not set(shape['required'])<=set(item):
    raise ValueError('Eligibility predicates require column/operator/value and optional value_type; unknown fields are not discarded.')
   if item.get('operator')=='=':item['operator']='=='
 elif 'eligibility_filters' in result:raise ValueError('eligibility_filters cannot be null.')
 if result.get('operator')=='=':result['operator']='=='
 for field,spec in PARAMETER_SCHEMA['properties'].items():
  if field not in result or field=='eligibility_filters':continue
  value=result[field]
  if spec.get('type')=='string' and not isinstance(value,str):raise ValueError(f'{field} must be text. '+contract_instructions())
  if 'enum' in spec and value not in spec['enum']:raise ValueError(f'{field} must be one of {spec["enum"]}. '+contract_instructions())
 return result


def calculate(df,p):
 p=normalize_parameters(p)
 for condition in p.get('eligibility_filters',[]):
  if isinstance(condition,dict) and {condition.get('column'),condition.get('value_column')}=={p['column'],p['value_column']}:
   raise ValueError('The event comparison belongs in column/operator/value_column, not eligibility filters; filtering by the event first would corrupt the denominator.')
 selected=filter_data(df,p['eligibility_filters']) if p.get('eligibility_filters') else df.copy()
 condition={k:v for k,v in p.items() if k not in {'eligibility_filters','matched_label'}}
 label=p.get('matched_label','Matched')
 if not isinstance(label,str) or not label.strip() or label in {'Eligible','Compared'}:raise ValueError('matched_label must be a distinct nonempty measure label.')
 # Validate both full columns even when no rows match eligibility filters.
 column_comparison(df,condition)
 left,right=p['column'],p['value_column']
 if p.get('value_type')=='date':
  a,b=parse_dates(selected[left],left),parse_dates(selected[right],right)
 else:a,b=selected[left],selected[right]
 eligible=a.notna();comparable=eligible & b.notna()
 matched=column_comparison(selected,condition)
 n=int(comparable.sum());count=int(matched.sum())
 facts={'filtered_count':len(selected),'eligible_count':int(eligible.sum()),'missing_actual_count':int(a.isna().sum()),
        'missing_comparison_count':int((eligible & b.isna()).sum()),'comparable_count':n,'matched_count':count,
        'percentage':100*count/n if n else None}
 row={'Eligible Count':facts['eligible_count'],'Missing Actual Date':facts['missing_actual_count'],
      'Missing Comparison Date':facts['missing_comparison_count'],'Compared Count':n,label+' Count':count,label+' Percentage':facts['percentage']}
 return {'analysis_kind':'comparison_summary','columns':list(row),'data':[row],'row_count':1,'comparison_audit':{**facts,'parameters':p},'units':{label+' Percentage':'%'}}


def explanation(result):
 f=result['comparison_audit'];p=f['parameters']
 percent=f"{f['percentage']:.6f}%" if f['percentage'] is not None else 'undefined (no comparable observations)'
 return (f"Comparison: {p['column']} {p['operator']} {p['value_column']}"
         + (' using calendar dates.' if p.get('date_part')=='date' else '.')
         + f" Filtered population: {f['filtered_count']:,}. Eligible with an actual value: {f['eligible_count']:,}. "
         f"Missing actual values: {f['missing_actual_count']:,}; missing comparison values among eligible observations: {f['missing_comparison_count']:,}. "
         f"Compared count (percentage denominator): {f['comparable_count']:,}. {p.get('matched_label','Matched')} count (numerator): {f['matched_count']:,}. Percentage: {percent}. "
         'With the strict > operator, equality is not a match. Missing comparisons are reported separately; no failed condition was omitted. Open result contains these same counts and percentage.')
