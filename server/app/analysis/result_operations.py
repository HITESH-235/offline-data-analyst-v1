"""Validated aggregation outputs: aliases, transformations, units and result limits."""
import copy
import json
import math
import re
import pandas as pd


def human(column):
 return re.sub(r'[_ .]+',' ',column).strip().title()


def output_definition(p):
 """Canonical aggregate identities shared by execution and request coverage."""
 from app.analysis.aggregate_specification import kernel
 specifications=p.get('measures',[])
 p=kernel(p)
 groups=p.get('group_by',[]);measures=p.get('aggregations',{})
 aliases=p.get('output_names',{})
 if not isinstance(aliases,dict) or any(c not in measures for c in aliases):raise ValueError('output_names maps input measure columns to output labels.')
 aliases=dict(aliases)
 for column,operation in measures.items():
  if operation in {'count','count_distinct'}:aliases.setdefault(column,human(re.sub(r'[_ .]?id$','',column,flags=re.I))+(' Distinct Count' if operation=='count_distinct' else ' Count'))
 transforms=p.get('transforms',[])
 if not isinstance(transforms,list):raise ValueError('transforms must be a list.')
 used=set()
 for t in transforms:
  if not isinstance(t,dict) or set(t)-{'column','divide_by','as','unit'} or not {'column','divide_by','as'}<=set(t):raise ValueError('Transform expects column, divide_by, as, and optional unit.')
  column=t['column'];divisor=t['divide_by']
  if column not in measures or column in used:raise ValueError('Transform must reference a distinct aggregate measure.')
  if type(divisor) not in (int,float) or not math.isfinite(divisor) or divisor==0:raise ValueError('divide_by must be a finite nonzero number.')
  if t.get('unit') is not None and not isinstance(t['unit'],str):raise ValueError('unit must be text.')
  aliases[column]=t['as'];used.add(column)
 names=[aliases.get(c,c) for c in measures]
 if any(not isinstance(n,str) or not n.strip() for n in names) or len(set(groups+names))!=len(groups+names):raise ValueError('Output labels must be nonempty and unique.')
 provenance={aliases.get(c,c):{'source_column':c,'operation':op,'role':'measure'} for c,op in measures.items()}
 units={}
 for t in transforms:
  name=aliases.get(t['column'],t['column']);provenance[name]['transform']=t.copy()
  if t.get('unit'):units[name]=t['unit']
 for m in specifications:
  provenance[m['label']]['measure_id']=m['id']
  if m.get('unit'):units[m['label']]=m['unit']
 for d in p.get('derived_measures',[]):
  provenance[d['name']]={'role':'measure','operation':'derived','derived':d['expression']}
  if d.get('unit'):units[d['name']]=d['unit']
 sort=p.get('sort_by')
 if sort=='count' and len(measures)==1 and next(iter(measures.values()))=='count':sort=names[0]
 return {'aliases':aliases,'columns':groups+names+[d['name'] for d in p.get('derived_measures',[])],
         'measure_provenance':provenance,'units':units,'sort_by':aliases.get(sort,sort)}


def apply_aggregation(df,p):
 from app.analysis.aggregate_specification import kernel
 definition=output_definition(p)
 p=kernel(p)
 allowed={'group_by','aggregations','sort_by','ascending','filters','fill_missing','output_names','transforms','limit','derived_measures'}
 if set(p)-allowed:raise ValueError(f'Unsupported aggregation fields: {sorted(set(p)-allowed)}')
 from app.analysis.aggregate_specification import kernel
 p=kernel(p)
 groups=p.get('group_by',[]);measures=p.get('aggregations',{})

 if set(groups)&set(measures):raise ValueError('Grouping and measure columns must be distinct.')
 from app.analysis.filtering import filter_data
 working=filter_data(df,p['filters']) if p.get('filters') else df.copy()
 fill=p.get('fill_missing',{})
 if not isinstance(fill,dict) or any(c not in groups for c in fill):raise ValueError('fill_missing maps grouping columns to scalar labels.')
 for column,value in fill.items():
  if not isinstance(value,(str,int,float,bool)) or isinstance(value,float) and not math.isfinite(value):raise ValueError('Missing-group labels must be finite scalars.')
  working[column]=working[column].fillna(value).replace('',value)
 aliases=definition['aliases'];names=[aliases.get(c,c) for c in measures];transforms=p.get('transforms',[])
 if groups:
  grouped=working.groupby(groups,as_index=False,dropna=False,sort=True)
  result=grouped.agg({c:(lambda s:s.sum(min_count=1)) if op=='sum' else 'nunique' if op=='count_distinct' else op for c,op in measures.items()}) if measures else grouped.size()
 else:
  result=pd.DataFrame([{c:working[c].sum(min_count=1) if op=='sum' else working[c].nunique(dropna=True) if op=='count_distinct' else working[c].agg(op) for c,op in measures.items()}])
 provenance=copy.deepcopy(definition['measure_provenance']);units=copy.deepcopy(definition['units'])
 for t in transforms:
  column=t['column'];result[column]=pd.to_numeric(result[column],errors='raise')/t['divide_by']
  out=aliases.get(column,column);provenance[out]['transform']=t.copy()
  if t.get('unit'):units[out]=t['unit']
 result=result.rename(columns=aliases)
 for derived in p.get('derived_measures',[]):
  if not isinstance(derived,dict) or set(derived)-{'name','expression','unit'} or not {'name','expression'}<=set(derived):raise ValueError('Derived measures require name/expression and optional unit.')
  name=derived['name']
  if not isinstance(name,str) or not name or name in result:raise ValueError('Derived output names must be distinct.')
  from app.analysis.calendar import evaluate
  result[name]=evaluate(derived['expression'],result)
  provenance[name]={'role':'measure','operation':'derived','derived':derived['expression']}
  if derived.get('unit'):units[name]=derived['unit']
 sort=definition['sort_by']
 if sort:
  if sort not in result:raise ValueError(f'Unknown result sort column {sort!r}. Available: {list(result.columns)}')
  result=result.sort_values([sort,*[g for g in groups if g!=sort]],ascending=[p.get('ascending',True),*[True for g in groups if g!=sort]],kind='stable')
 full_count=len(result);limit=p.get('limit')
 if limit is not None:
  if type(limit)!=int or not 1<=limit<=100000:raise ValueError('limit must be an integer from 1 to 100000.')
  if not sort:raise ValueError('A limited result requires sort_by to define the ranking.')
  result=result.head(limit)
 populations=[]
 if groups:
  for key,part in working.groupby(groups,dropna=False,sort=True):
   key=key if isinstance(key,tuple) else (key,)
   populations.append({'groups':{g:(None if pd.isna(v) else v.item() if hasattr(v,'item') else v) for g,v in zip(groups,key)},'count':len(part)})
 return {'group_populations':populations,'analysis_kind':'aggregation','columns':list(result.columns),
         'data':result.astype(object).where(pd.notna(result),None).to_dict(orient='records'),'row_count':len(result),
         'measure_provenance':provenance,'units':units,'source_observation_count':len(working),
         'result_scope':{'full_group_count':full_count,'returned_row_count':len(result),'limit':limit,'sort_by':sort,'ascending':p.get('ascending',True)},
         'transformation_audit':{'fill_missing':fill,'transforms':transforms,'output_names':aliases}}


def explanation(result):
 columns=result['columns'];rows=['| '+' | '.join(columns)+' |','|'+'---|'*len(columns)]
 for row in result['data'][:20]:
  rows.append('| '+' | '.join('Unavailable' if row[c] is None else f'{row[c]:,.2f}' if isinstance(row[c],float) else str(row[c]) for c in columns)+' |')
 scope=result['result_scope'];units=result.get('units',{})
 text=f"Returned {result['row_count']} of {scope['full_group_count']} result rows. "
 if scope['limit']:text+=f"The actual result is limited to {scope['limit']} rows, sorted by {scope['sort_by']}. "
 else:text+='The result contains all groups; a Top N chart selection only changes the chart display. '
 if units:text+='Units: '+', '.join(f'{c}: {u}' for c,u in units.items())+'. '
 for c,info in result['measure_provenance'].items():
  text+=f"{c} = "+(json.dumps(info['derived']) if info.get('derived') else f"{info['operation']}({info['source_column']})")
  if info.get('transform'):text+=f" / {info['transform']['divide_by']}"
  text+='. '
 if result['transformation_audit']['fill_missing']:text+='Missing grouping values were replaced with '+str(result['transformation_audit']['fill_missing'])+'. '
 return text+'\n\n'+'\n'.join(rows)+('\n\nThe remaining rows are available in Open result.' if result['row_count']>20 else '')
