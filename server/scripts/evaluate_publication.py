"""Freeze independent SQLite oracles, then evaluate the normal live HTTP path.

No model mocks, provider changes, or production patches. Artifacts are local to
workspace/evaluations; the evaluation project is visible in the application.
"""
import argparse,datetime,hashlib,json,sqlite3,subprocess,time,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
BASE='http://127.0.0.1:8001/api/v1'

def stamp():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def write(path,value):path.write_text(json.dumps(value,indent=2,ensure_ascii=False))
def sql(database,query):
 with sqlite3.connect((ROOT/'datasets'/database).resolve().as_uri()+'?mode=ro',uri=True) as db:
  db.row_factory=sqlite3.Row
  return [dict(r) for r in db.execute(query)]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
NET="d.UnitPrice*d.Quantity*(1-d.Discount)"
JOIN='FROM Orders o JOIN "Order Details" d ON o.OrderID=d.OrderID'

def prepare(folder):
 folder.mkdir(parents=True,exist_ok=False)
 cases=[]
 def add(id,dataset,question,database,query,population,formula,units,sources,scope,**extra):
  cases.append(dict(id=id,dataset=dataset,question=question,database=database,sql=query,expected=sql(database,query) if query else None,population=population,formula=formula,units=units,sources=sources,scope=scope,**extra))
 add('Q01','northwind.db::Products','Which ten products account for the greatest number of units sold over the entire database? Link Products to Order Details through ProductID, add Quantity for each ProductName, and return only those ten in descending order, with a horizontal bar chart.','northwind.db','SELECT p.ProductName,SUM(d.Quantity) AS Units FROM Products p JOIN "Order Details" d ON p.ProductID=d.ProductID GROUP BY p.ProductName ORDER BY Units DESC,p.ProductName LIMIT 10','Every joined order-detail line; no year/status filter','SUM(Quantity) per ProductName','units',['Products','Order Details'],{'table':'top 10','chart':'top 10'})
 add('Q02','northwind.db::Orders','For every ShipCountry, how many different CustomerID values occur in Orders? Count a customer once per shipping country even if they placed many orders. List every country from highest distinct-customer count to lowest; a table is sufficient.','northwind.db','SELECT ShipCountry,COUNT(DISTINCT CustomerID) AS DistinctCustomers FROM Orders GROUP BY ShipCountry ORDER BY DistinctCustomers DESC,ShipCountry','All Orders; distinct non-null CustomerID within each ShipCountry','COUNT(DISTINCT CustomerID)','customers',['Orders'],{'table':'all countries','chart':'not requested'})
 def revenue(id,q,years,grain,compare=False,reload=False):
  period="CAST(strftime('%m',o.OrderDate) AS INTEGER)" if grain=='month' else "(CAST(strftime('%m',o.OrderDate) AS INTEGER)+2)/3"
  query=f"SELECT CAST(strftime('%Y',o.OrderDate) AS INTEGER) AS Year,{period} AS Period,SUM({NET}) AS NetSales {JOIN} WHERE strftime('%Y',o.OrderDate) IN ({','.join(repr(str(y)) for y in years)}) GROUP BY 1,2 ORDER BY 1,2"
  add(id,'northwind.db::Orders',q,'northwind.db',query,'Order-detail lines whose joined OrderDate falls in '+str(years),f'SUM({NET}) per calendar {grain}', 'dataset currency units; no USD assumption',['Orders','Order Details'],{'table':12 if grain=='month' else 4,'comparison':compare,'chart':'chronological line','series':years},years=years,grain=grain,reload_before=reload)
 revenue('Q03','For calendar 2021, total net sales separately for each month using OrderDate. Join Orders with Order Details on OrderID and calculate UnitPrice times Quantity times (one minus Discount). Call the measure Net Sales, keep the original currency units, and draw a chronological line.',[2021],'month')
 revenue('Q04','Keep that same sales definition and year, but roll the months up into calendar quarters. Please calculate the four quarterly amounts and use a line chart.',[2021],'quarter')
 revenue('Q05','Put those four periods side by side with 2022, retaining 2021 and exactly the same net-sales formula. I want one row per quarter and a separate sales column and line for each year.',[2021,2022],'quarter',True)
 revenue('Q06','Switch that comparison back to months, leaving both years and the sales calculation as they are. Give twelve aligned month rows and two lines.',[2021,2022],'month',True,True)
 add('Q07','olist.db::order_payments','How much money was recorded for each payment_type across all Olist payment records? Sum payment_value_cents, convert the summed amounts to BRL by dividing by 100, call the measure Paid Amount (BRL), and list every payment type in descending amount order with a bar chart.','olist.db','SELECT payment_type,SUM(payment_value_cents)/100.0 AS PaidBRL FROM order_payments GROUP BY payment_type ORDER BY PaidBRL DESC,payment_type','All payment records; not just delivered orders','SUM(payment_value_cents)/100','BRL',['order_payments'],{'table':'all payment types','chart':'bar'})
 add('Q08','olist.db::order_items','Report merchandise sales for every product category, joining order_items and products by product_id. Treat a missing or blank product_category_name as Unknown. Use SUM(price_cents)/100 as Merchandise Sales (BRL), sorted largest first. The result table must retain every category; only the chart should show the leading ten.','olist.db',"SELECT COALESCE(NULLIF(p.product_category_name,''),'Unknown') AS Category,SUM(i.price_cents)/100.0 AS SalesBRL FROM order_items i JOIN products p ON i.product_id=p.product_id GROUP BY 1 ORDER BY SalesBRL DESC,Category",'Every item with its declared product relationship; missing category retained','SUM(price_cents)/100 per category; NULL/blank -> Unknown','BRL',['order_items','products'],{'table':'all categories','chart':'top 10'})
 add('Q09','olist.db::orders','Among orders marked delivered, what fraction reached the customer later than the estimated delivery date? Compare calendar days, so a delivery later in the day on the estimated date is on time. Show the delivered population, missing actual dates, missing estimates among orders with actual dates, comparable order count, late count, and late percentage. Do not drop missing dates without reporting them.','olist.db',"SELECT COUNT(*) AS Delivered,SUM(order_delivered_customer_date IS NULL) AS MissingActual,SUM(order_delivered_customer_date IS NOT NULL AND order_estimated_delivery_date IS NULL) AS MissingEstimate,COUNT(CASE WHEN order_delivered_customer_date IS NOT NULL AND order_estimated_delivery_date IS NOT NULL THEN 1 END) AS Comparable,SUM(CASE WHEN order_delivered_customer_date IS NOT NULL AND order_estimated_delivery_date IS NOT NULL AND date(order_delivered_customer_date)>date(order_estimated_delivery_date) THEN 1 ELSE 0 END) AS Late,100.0*SUM(CASE WHEN date(order_delivered_customer_date)>date(order_estimated_delivery_date) THEN 1 ELSE 0 END)/COUNT(CASE WHEN order_delivered_customer_date IS NOT NULL AND order_estimated_delivery_date IS NOT NULL THEN 1 END) AS LatePercent FROM orders WHERE order_status='delivered'",'Delivered orders; percentage denominator has both comparison dates','date(actual)>date(estimated); 100*Late/Comparable','orders and percent',['orders'],{'table':'population summary','chart':'not requested'})
 add('Q10','olist.db::order_financials','Audit payment coverage in order_financials without joining any line-item tables. Return three explicit numbers: total orders, orders with at least one payment record, and orders with no payment record. Calculate the missing count rather than leaving me to subtract it; a compact table is enough.','olist.db','SELECT COUNT(*) AS TotalOrders,SUM(has_payments) AS WithPayments,COUNT(*)-SUM(has_payments) AS WithoutPayments FROM order_financials','All one-row-per-order financial records','COUNT(*), SUM(has_payments), COUNT(*)-SUM(has_payments)','orders',['order_financials'],{'table':'three calculated counts','chart':'not requested'})
 add('Q11','olist.db::order_financials','For purchases made during 2018, show total paid BRL for every customer_state. Use order_financials joined to orders on order_id and then customers on customer_id. Keep only has_payments = 1, sum payment_total_cents and divide by 100, and rank all states by Paid Amount (BRL). Do not join order_items or multiply payments by item counts.','olist.db',"SELECT c.customer_state,SUM(f.payment_total_cents)/100.0 AS PaidBRL FROM order_financials f JOIN orders o ON f.order_id=o.order_id JOIN customers c ON o.customer_id=c.customer_id WHERE f.has_payments=1 AND o.order_purchase_timestamp>='2018-01-01' AND o.order_purchase_timestamp<'2019-01-01' GROUP BY c.customer_state ORDER BY PaidBRL DESC,c.customer_state",'One financial record per paid order purchased in 2018','SUM(payment_total_cents)/100 per customer_state','BRL',['order_financials','orders','customers'],{'table':'all states','chart':'not requested'})
 add('Q12','northwind.db::Products','Can the current application join northwind.db::Products to olist.db::products using ProductID = product_id and calculate the number of matched products? If cross-database joins or that relationship are unsupported, clearly decline this calculation instead of inventing a product mapping.','northwind.db',None,'Two different SQLite databases with unrelated identifier domains','Cross-database join is deliberately unsupported by V1; no approved relationship','no numeric result should be certified',['northwind.db::Products','olist.db::products'],{'table':'none','chart':'none'},expected_behavior='explicit rejection or incomplete, no certified count')
 # Independent controls supplement per-question SQL and preserve exact dataset identity.
 controls={
  'northwind_annual':sql('northwind.db',f"SELECT strftime('%Y',o.OrderDate) AS Year,SUM({NET}) AS Revenue {JOIN} WHERE strftime('%Y',o.OrderDate) IN ('2021','2022') GROUP BY 1"),
  'category_missing':sql('olist.db',"SELECT COUNT(*) AS ItemRows,SUM(i.price_cents)/100.0 AS SalesBRL FROM order_items i JOIN products p ON i.product_id=p.product_id WHERE p.product_category_name IS NULL OR p.product_category_name=''"),
  'population_counts':{name:sql(file,query) for name,file,query in [('northwind_orders','northwind.db','SELECT COUNT(*) AS count FROM Orders'),('northwind_lines','northwind.db','SELECT COUNT(*) AS count FROM "Order Details"'),('olist_payments','olist.db','SELECT COUNT(*) AS count FROM order_payments'),('olist_items','olist.db','SELECT COUNT(*) AS count FROM order_items')]}}
 manifest={'prepared_at':stamp(),'code_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'databases':{name:{'path':str(ROOT/'datasets'/name),'sha256':sha(ROOT/'datasets'/name)} for name in ['northwind.db','olist.db']},'cases':cases,'controls':controls}
 write(folder/'expected.json',manifest);write(folder/'expected.sha256.json',{'sha256':sha(folder/'expected.json')})
 print(json.dumps({'oracle':str(folder/'expected.json'),'cases':len(cases),'expected_rows':{c['id']:len(c['expected']) if c['expected'] is not None else None for c in cases},'controls':controls},indent=2))

def request(path,data=None):
 req=urllib.request.Request(BASE+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=660) as response:return json.load(response)

def run(folder):
 expected=folder/'expected.json';assert sha(expected)==json.loads((folder/'expected.sha256.json').read_text())['sha256']
 manifest=json.loads(expected.read_text())
 for name,info in manifest['databases'].items():assert sha(Path(info['path']))==info['sha256'],'Data changed after preparing oracle'
 state=folder/'run.json'
 if state.exists():run=json.loads(state.read_text())
 else:
  project=request('/projects/',{'name':folder.name+' '+datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
  run={'started_at':stamp(),'project':project,'model_path':'normal POST /api/v1/chat/message/stream','oracle_sha256':sha(expected)};write(state,run)
 project=run['project']['id'];print('Evaluation project:',project,flush=True)
 for case in manifest['cases']:
  target=folder/(case['id']+'.json')
  if target.exists():continue
  if case.get('reload_before'):
   # The browser restores these persisted endpoints; the next POST supplies no context.
   write(folder/'reload-before-Q06.json',{'at':stamp(),'messages':request('/projects/'+project+'/messages'),'analyses':request('/projects/'+project+'/analyses')})
  started=stamp();begin=time.monotonic();events=[];error=None
  print(case['id']+' starting: '+case['question'],flush=True)
  req=urllib.request.Request(BASE+'/chat/message/stream',data=json.dumps({'project_id':project,'dataset_id':case['dataset'],'message':case['question']}).encode(),headers={'Content-Type':'application/json'})
  try:
   with urllib.request.urlopen(req,timeout=660) as stream:
    for line in stream:
     if line.strip():
      event=json.loads(line);event['client_received_ms']=round((time.monotonic()-begin)*1000);events.append(event)
      print(case['id']+' '+event.get('stage','unknown')+' '+str(event['client_received_ms'])+'ms',flush=True)
  except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError) as e:error=str(e)
  end=stamp();latency=round((time.monotonic()-begin)*1000)
  record={'case':case['id'],'started_at':started,'finished_at':end,'latency_ms':latency,'first_progress_ms':events[0]['client_received_ms'] if events else None,'events':events,'transport_error':error}
  logs=subprocess.run(['docker','--context','desktop-linux','logs','--since',started,'--until',end,'offline-analyst-backend'],capture_output=True,text=True)
  # Existing application logs contain model draft text, not authorization headers.
  log=logs.stdout+logs.stderr;(folder/(case['id']+'.log')).write_text(log)
  record['observed_model_calls']={'planner':log.count('Classifying query intent:'),'table_selector':log.count('Selecting required tables for query:'),'agent':log.count('Agent turn ')}
  record['source_and_agent_log']=[line for line in log.splitlines() if any(x in line for x in ['Table selector output:','Resolved analysis source:','Agent turn ','Agent raw response:'])]
  result=next((e.get('result') for e in reversed(events) if e.get('result')),None);record['result']=result
  if result and result.get('planner_diagnostics'):
   record['observed_model_calls']['planner']=len(result['planner_diagnostics'])
  if result:
   saved=request('/projects/'+project+'/analyses');record['reopened_analysis']=next((s for s in saved if s['id']==result.get('id')),None)
   history=request('/projects/'+project+'/messages');record['restored_message']=next((m for m in history['messages'] if m['id']==result.get('id')),None)
  write(target,record)
  pack=(result or {}).get('analysis_package') or {}
  print(case['id']+' finished '+str(pack.get('status',(result or {}).get('analysis_status')))+' '+str(latency)+'ms',flush=True)
  if 'HTTP 429' in (result or {}).get('content',''):
   run['blocked']={'case':case['id'],'at':stamp(),'reason':'Provider HTTP 429; remaining questions were not attempted.'}
   write(state,run)
   raise SystemExit('Evaluation stopped on provider quota. Preserve this capture and use a new evidence directory after quota resets.')
 run['finished_at']=stamp();write(state,run)
 print(str(len(manifest['cases']))+' live requests recorded in '+str(folder),flush=True)

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','run']);parser.add_argument('folder',type=Path);args=parser.parse_args()
 {'prepare':prepare,'run':run}[args.action](args.folder.resolve())
