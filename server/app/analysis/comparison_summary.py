"""One validated comparison calculation, with explicit population/coverage counts."""
from app.analysis.filtering import filter_data,parse_dates,column_comparison
import copy
import json
import pandas as pd
from app.services.request_control import checkpoint

from app.analysis.operations import Comparison
PARAMETER_SCHEMA=Comparison.model_json_schema()
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
         'Use group_by for grouped comparisons and sort_by=percentage, ascending=false to rank rates. The single combined table retains every group and reports zero denominators as null (sorted last). Missing comparison dates are counted only among rows with an actual date. count_label and comparison_label customize generic measure labels. The operation excludes either missing date from the denominator.')


def normalize_parameters(p):
 from app.analysis.operations import validate
 return validate('comparison_summary',p,'$.comparison_summary')


def calculate(df,p):
 p=normalize_parameters(p)
 for condition in p.get('eligibility_filters',[]):
  if isinstance(condition,dict) and {condition.get('column'),condition.get('value_column')}=={p['column'],p['value_column']}:
   raise ValueError('The event comparison belongs in column/operator/value_column, not eligibility filters; filtering by the event first would corrupt the denominator.')
 selected=(filter_data(df,p['eligibility_filters']) if p.get('eligibility_filters') else df.copy()).reset_index(drop=True)
 condition={k:p[k] for k in ('column','operator','value_column','value_type','date_part') if k in p}
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
 if p.get('group_by'):
  return grouped(selected,p,a,b,matched,facts)
 row={'Eligible Count':facts['eligible_count'],'Missing Actual Date':facts['missing_actual_count'],
      'Missing Comparison Date':facts['missing_comparison_count'],'Compared Count':n,label+' Count':count,label+' Percentage':facts['percentage']}
 return {'analysis_kind':'comparison_summary','columns':list(row),'data':[row],'row_count':1,'measure_provenance':{
         'Eligible Count':{'operation':'eligible_count','source_column':left},
         'Missing Actual Date':{'operation':'missing_actual_count','source_column':left},
         'Missing Comparison Date':{'operation':'missing_comparison_count','source_column':right},
         'Compared Count':{'operation':'comparable_count','source_column':left},
         label+' Count':{'operation':'matched_count','source_column':left},
         label+' Percentage':{'operation':'percentage','source_column':left}},'comparison_audit':{**facts,'parameters':p},'units':{label+' Percentage':'%'}}


def sort_column(parameters,key):
 grouped=bool(parameters.get('group_by'));unit=parameters.get('count_label','Count') if grouped else 'Count'
 label=parameters.get('matched_label','Matched')
 return {'percentage':label+' Percentage','matched_count':label+' '+unit,
         'comparable_count':'Comparable '+unit if grouped else 'Compared Count'}.get(key,key)


def measure_requirements(parameters):
 """Exact native output identities for a complete comparison operation."""
 p=parameters
 counts=[('comparable_count',sort_column(p,'comparable_count')),
         ('matched_count',sort_column(p,'matched_count')),('percentage',sort_column(p,'percentage'))]
 missing=[('missing_actual_count','Missing Actual Date'),
          ('missing_comparison_count','Missing '+(p.get('comparison_label','Comparison') if p.get('group_by') else 'Comparison')+' Date')]
 if not p.get('group_by'):counts=[('eligible_count','Eligible Count'),*missing,*counts]
 else:counts+=missing
 return [{'operation':op,'output':name,**({'unit':'%'} if op=='percentage' else {})} for op,name in counts]


def grouped(selected,p,a,b,matched,facts):
 groups=p['group_by']
 if len(set(groups))!=len(groups) or any(c not in selected for c in groups):
  raise ValueError('group_by must contain distinct existing columns.')
 label=p.get('matched_label','Matched');unit=p.get('count_label','Count')
 comparable_name='Comparable '+unit;matched_name=label+' '+unit;percentage_name=label+' Percentage'
 missing_name='Missing '+p.get('comparison_label','Comparison')+' Date'
 columns=[*groups,comparable_name,matched_name,percentage_name,'Missing Actual Date',missing_name]
 if len(set(columns))!=len(columns):raise ValueError('Grouping and measure labels must be distinct.')
 # Sum masks over the full eligible population, never the event-filtered subset.
 # This retains groups with zero events and groups with no comparable dates.
 masks={'filtered_count':pd.Series(1,index=selected.index),'eligible_count':a.notna().astype(int),
        'missing_actual_count':a.isna().astype(int),'missing_comparison_count':(a.notna() & b.isna()).astype(int),
        'comparable_count':(a.notna() & b.notna()).astype(int),'matched_count':matched.astype(int)}
 prefix='__comparison_'
 while any((prefix+k) in selected for k in masks):prefix='_'+prefix
 work=selected[groups].copy()
 for k,mask in masks.items():work[prefix+k]=mask
 checkpoint()
 totals=work.groupby(groups,dropna=False,observed=True,sort=True)[[prefix+k for k in masks]].sum().reset_index()
 rows=[];audits=[]
 for values in totals.to_dict('records'):
  keys={g:None if pd.isna(values[g]) else values[g] for g in groups}
  f={k:int(values[prefix+k]) for k in masks};n=f['comparable_count']
  f['percentage']=100*f['matched_count']/n if n else None
  audits.append({**keys,**f})
  rows.append({**keys,comparable_name:n,matched_name:f['matched_count'],percentage_name:f['percentage'],
               'Missing Actual Date':f['missing_actual_count'],missing_name:f['missing_comparison_count']})
 sort_name=sort_column(p,p.get('sort_by'))
 if sort_name:
  rows.sort(key=lambda row:(row[sort_name] is None, (row[sort_name] if p.get('ascending',False) else -row[sort_name]) if row[sort_name] is not None else 0))
 checkpoint()
 return {'analysis_kind':'comparison_summary','columns':columns,'data':rows,'row_count':len(rows),
         'source_observation_count':len(selected),'units':{percentage_name:'%'},
         'comparison_audit':{**facts,'parameters':p,'groups':audits,
             'missing_comparison_population':'rows with an actual value within the eligibility-filtered population',
             'percentage_formula':{'numerator':matched_name,'denominator':comparable_name,'scale':100}},
         'measure_provenance':{comparable_name:{'operation':'comparable_count','source_column':p['column']},matched_name:{'operation':'matched_count','source_column':p['column']},
                               percentage_name:{'operation':'percentage','source_column':p['column']},
                               'Missing Actual Date':{'operation':'missing_actual_count','source_column':p['column']},
                               missing_name:{'operation':'missing_comparison_count','source_column':p['value_column']}},
         'result_scope':{'full_group_count':len(rows),'returned_row_count':len(rows),'limit':None,
                         'sort_by':sort_name,'ascending':p.get('ascending',False),'nulls':'last'},
         'visualization_blueprint':{'chart_type':'bar','x':groups[0],'y':percentage_name}}


def explanation(result):
 f=result['comparison_audit'];p=f['parameters']
 if p.get('group_by'):
  from app.services.answer_summary import comparison_summary
  return comparison_summary(result)
 percent=f"{f['percentage']:.6f}%" if f['percentage'] is not None else 'undefined (no comparable observations)'
 return (f"Comparison: {p['column']} {p['operator']} {p['value_column']}"
         + (' using calendar dates.' if p.get('date_part')=='date' else '.')
         + f" Filtered population: {f['filtered_count']:,}. Eligible with an actual value: {f['eligible_count']:,}. "
         f"Missing actual values: {f['missing_actual_count']:,}; missing comparison values among eligible observations: {f['missing_comparison_count']:,}. "
         f"Compared count (percentage denominator): {f['comparable_count']:,}. {p.get('matched_label','Matched')} count (numerator): {f['matched_count']:,}. Percentage: {percent}. "
         'With the strict > operator, equality is not a match. Missing comparisons are reported separately; no failed condition was omitted. Open result contains these same counts and percentage.')
