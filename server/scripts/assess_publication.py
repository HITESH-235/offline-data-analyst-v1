"""Value/storage checks for the frozen live publication evaluation.
Semantic judgement remains manual and is reported separately from these checks.
"""
import argparse,json,math,re
from pathlib import Path

def close(a,b):
 if a is None or b is None:return a is b
 return isinstance(a,(float,int)) and not isinstance(a,bool) and math.isclose(a,b,rel_tol=1e-10,abs_tol=.00001)
def only_measure(data,group):
 candidates=[c for c in data[0] if c!=group and any(isinstance(row.get(c),(float,int)) for row in data)] if data else []
 return candidates[0] if len(candidates)==1 else None

def check_values(case,result):
 expected=case['expected'];table=result.get('results') or {};rows=table.get('data') or []
 if case['id']=='Q12':return None,'Unsupported request: a certified numeric answer is not expected.'
 if not rows:
  context=result.get('analysis_context') or {}
  if case.get('years') and context.get('years') and context['years']!=case['years']:return False,'Executed context has wrong years '+str(context['years'])+'; table was discarded before publication.'
  return None,'No published table to compare.'
 if case['id'] in ['Q01','Q02','Q07','Q08','Q11','H01','H02','H05','H06','H07']:
  group,oracle_group,oracle_measure={'Q01':('ProductName','ProductName','Units'),'Q02':('ShipCountry','ShipCountry','DistinctCustomers'),'Q07':('payment_type','payment_type','PaidBRL'),'Q08':('product_category_name','Category','SalesBRL'),'Q11':('customer_state','customer_state','PaidBRL'),'H01':('CategoryName','CategoryName','ProductCount'),'H02':('seller_state','seller_state','FreightBRL'),'H05':('customer_state','customer_state','People'),'H06':('seller_state','seller_state','FreightBRL'),'H07':('payment_installments','payment_installments','PaidBRL')}[case['id']]
  if group not in rows[0]:return False,'Missing grouping column '+group
  measure=only_measure(rows,group)
  if not measure:return None,'Multiple/no numeric columns; manual mapping required.'
  actual={row[group]:row.get(measure) for row in rows};oracle={row[oracle_group]:row[oracle_measure] for row in expected}
  if len(rows)!=len(expected) or set(actual)!=set(oracle):return False,f'Output groups differ: actual={len(rows)}, expected={len(expected)}'
  mismatches=[key for key in oracle if not close(actual[key],oracle[key])]
  if mismatches:return False,'Values differ for '+str(mismatches[:5])
  values=[row[measure] for row in rows]
  if values!=sorted(values,reverse=True):return False,'Values agree but requested descending ordering is wrong.'
  return True,f'All {len(rows)} groups and values agree with SQLite; descending ordering agrees.'
 if case['id'] in ['Q03','Q04','Q05','Q06']:
  period='Month' if case['grain']=='month' else 'Quarter';n=12 if period=='Month' else 4
  if period not in table.get('columns',[]):return False,'Missing expected period column '+period
  years=case['years'];comp=case['scope']['comparison'];wanted=n if comp else n*len(years)
  if len(rows)!=wanted:return False,f'Expected {wanted} rows; got {len(rows)}.'
  series=[c for c in table['columns'] if c!=period]
  if len(series)!=len(years) if comp else len(series)!=1:return False,'Wrong number of year series.'
  lookup={(r['Year'],r['Period']):r['NetSales'] for r in expected}
  for year in years:
   key=next((s for s in series if str(year) in s),None) if comp else series[0]
   if key is None:return False,'Missing year '+str(year)
   for i,row in enumerate(rows):
    p=i+1
    if not close(row[key],lookup.get((year,p),0)):return False,f'Value mismatch in {year}, period {p}.'
  ctx=table.get('analysis_context') or {};chart=table.get('calendar_chart') or {}
  if ctx and (ctx.get('years')!=years or ctx.get('grain')!=case['grain']):return False,'Published context disagrees with requested years/grouping.'
  if chart and chart.get('series')!=series:return False,'Chart series disagree with table columns.'
  return True,'Every period/year value agrees with SQLite; expected series count is present.'
 if case['id'] in ['Q09','H03','H08']:
  audit=table.get('comparison_audit')
  if not audit:return None,'No canonical comparison audit; manual mapping required.'
  names={'filtered_count':'Delivered','missing_actual_count':'MissingActual','missing_comparison_count':'MissingEstimate','comparable_count':'Comparable','matched_count':'Late','percentage':'LatePercent'}
  if case['id'] in ['H03','H08']:names={'filtered_count':'Population','missing_actual_count':'MissingActual','missing_comparison_count':'MissingComparison','comparable_count':'Comparable','matched_count':'Matched','percentage':'Percentage'}
  wrong={key:(audit.get(key),expected[0][value]) for key,value in names.items() if not close(audit.get(key),expected[0][value])}
  params=audit.get('parameters') or {}
  if params.get('date_part')!='date' or params.get('operator')!='>':return False,'Wrong date normalization or comparison.'
  return (False,str(wrong)) if wrong else (True,'All population, missing-date, numerator/denominator and percentage values agree with SQLite.')
 if case['id']=='H04':
  if len(rows)!=4 or table.get('analysis_context',{}).get('years')!=[2020]:return False,'Wrong year or quarter scope.'
  measure=only_measure(rows,'Quarter')
  if not measure:return False,'Expected one freight measure.'
  return all(close(row[measure],expected[i]['Freight']) for i,row in enumerate(rows)),'All four freight sums compared with SQLite.'
 if case['id']=='Q10':
  mapped={}
  tables=(result.get('analysis_package') or {}).get('tables',[])
  for entry in tables:
   t=entry['result'];prov=t.get('measure_provenance') or {};data=t.get('data') or []
   for col,p in prov.items():
    if p.get('source_column')=='order_id' and p.get('operation') in {'count','count_distinct'} and data:
     if 'has_payments' not in t['columns']:
      filters=entry.get('parameters',{}).get('filters',[])
      flag=next((f.get('value') for f in filters if f.get('column')=='has_payments' and f.get('operator')=='=='),None)
      record_filter=next((f for f in filters if f.get('column')=='payment_record_count'),None)
      if record_filter and record_filter.get('operator')=='>' and record_filter.get('value')==0:flag=1
      elif record_filter and record_filter.get('operator')=='==' and record_filter.get('value')==0:flag=0
      if flag==1:mapped['WithPayments']=data[0].get(col)
      elif flag==0:mapped['WithoutPayments']=data[0].get(col)
      elif not filters:mapped['TotalOrders']=data[0].get(col)
     elif 'has_payments' in t['columns']:
      for row in data:
       if row['has_payments']==1:mapped['WithPayments']=row[col]
       elif row['has_payments']==0:mapped['WithoutPayments']=row[col]
    elif p.get('source_column')=='has_payments' and p.get('operation')=='sum':mapped['WithPayments']=data[0].get(col)
    elif p.get('operation')=='derived':mapped['WithoutPayments']=data[0].get(col)
  if set(mapped)!=set(expected[0]):return False,'The three explicitly requested calculations are not all present.'
  return all(close(mapped[k],v) for k,v in expected[0].items()),'Three counts calculated across related tables: '+str(mapped)
 return None,'Manual assessment required.'

def assess(folder):
 manifest=json.loads((folder/'expected.json').read_text());summary=[]
 for case in manifest['cases']:
  path=folder/(case['id']+'.json')
  if not path.exists():continue
  record=json.loads(path.read_text());result=record.get('result') or {};pack=result.get('analysis_package') or {};status='clarification' if result.get('clarification_required') else pack.get('status',result.get('analysis_status','no result'))
  calculated,note=check_values(case,result)
  saved=record.get('reopened_analysis');restored=record.get('restored_message');metadata=json.loads(restored.get('metadata_json') or '{}') if restored else {}
  restoration={
   'chat_content':restored.get('content')==result.get('content') if restored else None,
   'chat_package':metadata.get('analysis_package')==result.get('analysis_package') if restored else None,
   'saved_package':saved.get('analysisPackage')==pack if saved else None,
   'saved_table':saved.get('result')==result.get('results') if saved else None}
  steps=(result.get('calculation') or {}).get('steps',[])
  item={'id':case['id'],'status':status,'calculation_matches_sqlite':calculated,'calculation_note':note,'latency_ms':record['latency_ms'],'first_progress_ms':record['first_progress_ms'],'observed_model_calls':record['observed_model_calls'],'steps':[{'tool':s['tool'],'status':s['status'],'parameters':s.get('parameters'), 'error':s.get('error'),'execution_skipped':s.get('execution_skipped')} for s in steps],'storage':restoration,'content':result.get('content'),'requirements':pack.get('requirements'),'chart_specs':pack.get('charts'),'incomplete_reasons':pack.get('incomplete_reasons')}
  summary.append(item)
 (folder/'assessment.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False))
 for r in summary:
  print(f"{r['id']} {r['status']} sqlite={r['calculation_matches_sqlite']} {r['latency_ms']/1000:.2f}s calls={sum(r['observed_model_calls'].values())} tools={[(s['tool'],s['status']) for s in r['steps']]}")
 return summary
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('folder',type=Path);args=p.parse_args();assess(args.folder)
