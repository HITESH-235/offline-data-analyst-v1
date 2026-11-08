"""Explicit, repeatable import of the nine audited Olist CSVs. Standard library only."""
import argparse
import csv
import hashlib
import json
import math
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime
from decimal import Decimal
from pathlib import Path

APPLICATION_ID = 0x4F4C4953
SCHEMA_VERSION = 1
FACT_TABLES = {'order_items', 'order_payments', 'order_reviews', 'order_financials'}

# Source columns are preserved except monetary columns, explicitly converted to cents.
SPECS = {
 'customers': ('olist_customers_dataset.csv', '''customer_id TEXT PRIMARY KEY NOT NULL, customer_unique_id TEXT NOT NULL, customer_zip_code_prefix TEXT NOT NULL, customer_city TEXT NOT NULL, customer_state TEXT NOT NULL''', ''),
 'orders': ('olist_orders_dataset.csv', '''order_id TEXT PRIMARY KEY NOT NULL, customer_id TEXT NOT NULL, order_status TEXT NOT NULL, order_purchase_timestamp TIMESTAMP NOT NULL, order_approved_at TIMESTAMP, order_delivered_carrier_date TIMESTAMP, order_delivered_customer_date TIMESTAMP, order_estimated_delivery_date TIMESTAMP NOT NULL''', ', FOREIGN KEY(customer_id) REFERENCES customers(customer_id)'),
 'products': ('olist_products_dataset.csv', '''product_id TEXT PRIMARY KEY NOT NULL, product_category_name TEXT, product_name_lenght INTEGER, product_description_lenght INTEGER, product_photos_qty INTEGER, product_weight_g INTEGER, product_length_cm INTEGER, product_height_cm INTEGER, product_width_cm INTEGER''', ''),
 'sellers': ('olist_sellers_dataset.csv', '''seller_id TEXT PRIMARY KEY NOT NULL, seller_zip_code_prefix TEXT NOT NULL, seller_city TEXT NOT NULL, seller_state TEXT NOT NULL''', ''),
 'order_items': ('olist_order_items_dataset.csv', '''order_id TEXT NOT NULL, order_item_id INTEGER NOT NULL, product_id TEXT NOT NULL, seller_id TEXT NOT NULL, shipping_limit_date TIMESTAMP NOT NULL, price_cents INTEGER NOT NULL, freight_value_cents INTEGER NOT NULL''', ', PRIMARY KEY(order_id,order_item_id), FOREIGN KEY(order_id) REFERENCES orders(order_id), FOREIGN KEY(product_id) REFERENCES products(product_id), FOREIGN KEY(seller_id) REFERENCES sellers(seller_id)'),
 'order_payments': ('olist_order_payments_dataset.csv', '''order_id TEXT NOT NULL, payment_sequential INTEGER NOT NULL, payment_type TEXT NOT NULL, payment_installments INTEGER NOT NULL, payment_value_cents INTEGER NOT NULL''', ', PRIMARY KEY(order_id,payment_sequential), FOREIGN KEY(order_id) REFERENCES orders(order_id)'),
 'order_reviews': ('olist_order_reviews_dataset.csv', '''review_id TEXT NOT NULL, order_id TEXT NOT NULL, review_score INTEGER NOT NULL CHECK(review_score BETWEEN 1 AND 5), review_comment_title TEXT, review_comment_message TEXT, review_creation_date TIMESTAMP NOT NULL, review_answer_timestamp TIMESTAMP NOT NULL''', ', PRIMARY KEY(order_id,review_id), FOREIGN KEY(order_id) REFERENCES orders(order_id)'),
 'category_translation': ('product_category_name_translation.csv', '''product_category_name TEXT PRIMARY KEY NOT NULL, product_category_name_english TEXT NOT NULL''', ''),
 'geolocation': ('olist_geolocation_dataset.csv', '''geolocation_row_id INTEGER PRIMARY KEY, geolocation_zip_code_prefix TEXT NOT NULL, geolocation_lat REAL NOT NULL, geolocation_lng REAL NOT NULL, geolocation_city TEXT NOT NULL, geolocation_state TEXT NOT NULL''', ''),
}
MONEY = {'price': 'price_cents', 'freight_value': 'freight_value_cents', 'payment_value': 'payment_value_cents'}


def sha256(path):
 digest=hashlib.sha256()
 with Path(path).open('rb') as stream:
  for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
 return digest.hexdigest()


def validate_join_grain(tables):
 facts=FACT_TABLES.intersection(tables)
 if len(facts)>1:
  raise ValueError('Olist join would mix analysis grains: '+', '.join(sorted(facts))+'. Use order_financials with orders/customers for order-level totals, or analyze each raw fact table separately. Joining items, payments, reviews or order-level totals together can multiply measures; explicit pre-aggregation/allocation is required.')


def _columns(definition):
 return [(field.strip().split()[0],field.strip().split()[1]) for field in definition.split(',')]


def convert(value, column, kind):
 if value=='':return None
 if column.endswith('_cents'):
  decimal=Decimal(value)
  if not decimal.is_finite() or decimal*100!=(decimal*100).to_integral_value():raise ValueError('Money must be finite, exact cents.')
  amount=int(decimal*100)
  if not -(2**63)<=amount<2**63:raise ValueError('Money exceeds SQLite integer range.')
  return amount
 if kind=='INTEGER':
  if not value.lstrip('-').isdigit():raise ValueError('Expected an integer.')
  return int(value)
 if kind=='REAL':
  number=float(value)
  if not math.isfinite(number):raise ValueError('Expected a finite coordinate.')
  if not (-90<=number<=90 if column.endswith('_lat') else -180<=number<=180):raise ValueError('Coordinate is outside world bounds.')
  return number
 if kind=='TIMESTAMP':datetime.fromisoformat(value)
 if column.endswith('_zip_code_prefix') and (len(value)!=5 or not value.isdigit()):raise ValueError('ZIP prefix must be five digits.')
 if column.endswith('_id') and column!='geolocation_row_id' and (len(value)!=32 or any(c not in '0123456789abcdef' for c in value)):raise ValueError('Expected a 32-character hexadecimal ID.')
 return value


def _import_table(db, source, table, spec):
 filename,definition,constraints=spec
 db.execute(f'CREATE TABLE "{table}" ({definition}{constraints})')
 columns=_columns(definition)
 if table=='geolocation':columns=columns[1:]  # Every source row is retained, including exact duplicates.
 reverse={target:original for original,target in MONEY.items()}
 headers=[reverse.get(name,name) for name,_ in columns]
 query=f'INSERT INTO "{table}" ({",".join(name for name,_ in columns)}) VALUES ({",".join("?" for _ in columns)})'
 total=0;batch=[]
 with (source/filename).open(newline='',encoding='utf-8-sig') as stream:
  reader=csv.DictReader(stream)
  if reader.fieldnames!=headers:raise ValueError(f'{filename}: unexpected CSV headers; expected {headers!r}.')
  for row in reader:
   try:
    if None in row or any(value is None for value in row.values()):raise ValueError('Malformed CSV row.')
    batch.append([convert(row[reverse.get(name,name)],name,kind) for name,kind in columns])
   except (ValueError,ArithmeticError) as error:raise ValueError(f'{filename}, record {total+1}: {error}') from error
   total+=1
   if len(batch)==2000:db.executemany(query,batch);batch=[]
  if batch:db.executemany(query,batch)
 return total


def _summary(db):
 db.execute('''CREATE TABLE order_financials (
 order_id TEXT PRIMARY KEY NOT NULL REFERENCES orders(order_id),
 item_count INTEGER NOT NULL, item_total_cents INTEGER, freight_total_cents INTEGER,
 payment_record_count INTEGER NOT NULL, payment_total_cents INTEGER,
 has_items INTEGER NOT NULL, has_payments INTEGER NOT NULL)''')
 db.execute('''INSERT INTO order_financials
 SELECT o.order_id,COALESCE(i.n,0),i.price,i.freight,COALESCE(p.n,0),p.paid,
 CASE WHEN i.n IS NULL THEN 0 ELSE 1 END,CASE WHEN p.n IS NULL THEN 0 ELSE 1 END
 FROM orders o
 LEFT JOIN (SELECT order_id,COUNT(*) n,SUM(price_cents) price,SUM(freight_value_cents) freight FROM order_items GROUP BY order_id) i ON i.order_id=o.order_id
 LEFT JOIN (SELECT order_id,COUNT(*) n,SUM(payment_value_cents) paid FROM order_payments GROUP BY order_id) p ON p.order_id=o.order_id''')
 for table,column in [('customers','customer_unique_id'),('customers','customer_zip_code_prefix'),('orders','customer_id'),('orders','order_purchase_timestamp'),('order_items','product_id'),('order_items','seller_id'),('products','product_category_name'),('sellers','seller_zip_code_prefix'),('order_reviews','review_id'),('geolocation','geolocation_zip_code_prefix')]:
  db.execute(f'CREATE INDEX "idx_{table}_{column}" ON "{table}"("{column}")')


def validate_database(db):
 if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Database integrity check failed.')
 if db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('Foreign key check failed.')
 if db.execute('SELECT COUNT(*) FROM order_financials').fetchone()!=db.execute('SELECT COUNT(*) FROM orders').fetchone():raise ValueError('Order summary row count differs.')
 for raw,col,summary in [('order_items','price_cents','item_total_cents'),('order_items','freight_value_cents','freight_total_cents'),('order_payments','payment_value_cents','payment_total_cents')]:
  if db.execute(f'SELECT SUM({col}) FROM {raw}').fetchone()!=db.execute(f'SELECT SUM({summary}) FROM order_financials').fetchone():raise ValueError(f'{raw} totals do not reconcile.')
 return {'item_total_cents':db.execute('SELECT SUM(price_cents) FROM order_items').fetchone()[0],
         'freight_total_cents':db.execute('SELECT SUM(freight_value_cents) FROM order_items').fetchone()[0],
         'payment_total_cents':db.execute('SELECT SUM(payment_value_cents) FROM order_payments').fetchone()[0],
         'orders_without_items':db.execute('SELECT COUNT(*) FROM order_financials WHERE has_items=0').fetchone()[0],
         'orders_without_payments':db.execute('SELECT COUNT(*) FROM order_financials WHERE has_payments=0').fetchone()[0]}


def import_olist(source, output, receipt, replace=False):
 source=Path(source).resolve();output=Path(output).resolve();receipt=Path(receipt).resolve()
 if output.name!='olist.db':raise ValueError('This importer only publishes a database named olist.db.')
 fingerprints={spec[0]:sha256(source/spec[0]) for spec in SPECS.values()}
 identity={'importer':'olist-sqlite','schema_version':SCHEMA_VERSION,'source_sha256':fingerprints}
 if output.exists():
  previous=json.loads(receipt.read_text()) if receipt.is_file() else {}
  if all(previous.get(k)==v for k,v in identity.items()) and previous.get('database_sha256')==sha256(output):
   return {**previous,'unchanged':True}
  if not replace:raise ValueError('olist.db already exists with different inputs or an unverified receipt. Use --replace after reviewing changes.')
  with closing(sqlite3.connect(output.as_uri()+'?mode=ro',uri=True)) as existing:
   if existing.execute('PRAGMA application_id').fetchone()[0]!=APPLICATION_ID:raise ValueError('Refusing to replace a database not created by the Olist importer.')
 output.parent.mkdir(parents=True,exist_ok=True);receipt.parent.mkdir(parents=True,exist_ok=True)
 # Hidden, unsupported suffix: startup/catalog cannot discover a partially written database.
 handle,staged=tempfile.mkstemp(prefix='.olist-import-',suffix='.staging',dir=output.parent);os.close(handle)
 try:
  with closing(sqlite3.connect(staged)) as db:
   db.execute('PRAGMA foreign_keys=ON');db.execute(f'PRAGMA application_id={APPLICATION_ID}');db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
   with db:
    counts={table:_import_table(db,source,table,spec) for table,spec in SPECS.items()}
    _summary(db)
   totals=validate_database(db)
  if fingerprints!={name:sha256(source/name) for name in fingerprints}:raise ValueError('Source CSVs changed during import.')
  report={**identity,'source_directory':str(source),'output':str(output),'row_counts':counts,
          'units':'All *_cents monetary fields are integer BRL cents. Divide aggregated sums by 100 for BRL.',
          'money_column_mapping':MONEY,'totals':totals,'database_sha256':sha256(staged)}
  os.replace(staged,output)
  temp_receipt=receipt.with_suffix(receipt.suffix+'.tmp');temp_receipt.write_text(json.dumps(report,indent=2)+'\n');os.replace(temp_receipt,receipt)
  return report
 finally:
  if os.path.exists(staged):os.unlink(staged)


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 project=Path(__file__).resolve().parents[3]
 parser.add_argument('--source',type=Path,default=project/'datasets/brazilian-ecommerce')
 parser.add_argument('--output',type=Path,default=project/'datasets/olist.db')
 parser.add_argument('--receipt',type=Path,default=project/'workspace/imports/olist.json')
 parser.add_argument('--replace',action='store_true',help='Replace an existing importer-owned DB after input/schema changes. Stop backend first.')
 args=parser.parse_args()
 print(json.dumps(import_olist(args.source,args.output,args.receipt,args.replace),indent=2))
