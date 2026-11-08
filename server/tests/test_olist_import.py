import csv
from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from app.services.olist_import import SPECS,MONEY,APPLICATION_ID,_columns,import_olist,validate_join_grain,sha256


class OlistImportTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.source=self.root/'csv';self.source.mkdir()
  self.output=self.root/'olist.db';self.receipt=self.root/'receipts'/'olist.json'
  ids={'customer_id':'a'*32,'customer_unique_id':'d'*32,'order_id':'b'*32,'product_id':'c'*32,'seller_id':'e'*32,'review_id':'f'*32}
  reverse={v:k for k,v in MONEY.items()}
  for table,(filename,definition,_) in SPECS.items():
   columns=_columns(definition)
   if table=='geolocation':columns=columns[1:]
   headers=[reverse.get(c,c) for c,_ in columns];row={}
   for name,kind in columns:
    original=reverse.get(name,name)
    row[original]=ids.get(name,'01001' if name.endswith('_zip_code_prefix') else '2017-01-01 12:00:00' if kind=='TIMESTAMP' else '1.50' if name.endswith('_cents') else '5' if name=='review_score' else '1' if kind=='INTEGER' else '-23.5' if name.endswith('_lat') else '-46.6' if name.endswith('_lng') else 'category')
   rows=[row]
   if table=='order_items':rows=[{**row,'price':'1.00','freight_value':'0.10'},{**row,'order_item_id':'2','price':'2.00','freight_value':'0.20'}]
   if table=='order_payments':rows=[row,{**row,'payment_sequential':'2'}]
   if table=='orders':rows=[row,{**row,'order_id':'9'*32}]
   if table=='order_reviews':rows=[row,{**row,'order_id':'9'*32}]
   if table=='geolocation':rows=[row,row.copy()]
   with (self.source/filename).open('w',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=headers);writer.writeheader();writer.writerows(rows)
 def tearDown(self):self.tmp.cleanup()
 def run_import(self,replace=False):return import_olist(self.source,self.output,self.receipt,replace)
 def test_types_keys_duplicates_summary_and_repeat_noop(self):
  report=self.run_import();before=(sha256(self.output),self.output.stat().st_mtime_ns)
  self.assertEqual(report['totals']['item_total_cents'],300)
  self.assertEqual(report['totals']['payment_total_cents'],300)
  self.assertEqual(report['totals']['orders_without_items'],1)
  self.assertEqual(report['totals']['orders_without_payments'],1)
  with closing(sqlite3.connect(self.output)) as db:
   self.assertEqual(db.execute('PRAGMA application_id').fetchone()[0],APPLICATION_ID)
   self.assertEqual(db.execute('SELECT customer_zip_code_prefix,typeof(customer_zip_code_prefix) FROM customers').fetchone(),('01001','text'))
   self.assertEqual(db.execute('SELECT COUNT(*) FROM geolocation').fetchone()[0],2)
   self.assertEqual(db.execute('SELECT COUNT(DISTINCT review_id),COUNT(*) FROM order_reviews').fetchone(),(1,2))
   self.assertEqual(db.execute('SELECT item_total_cents,payment_total_cents FROM order_financials WHERE has_items=1').fetchone(),(300,300))
   self.assertIsNone(db.execute('SELECT payment_total_cents FROM order_financials WHERE has_payments=0').fetchone()[0])
   self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
  self.assertTrue(self.run_import()['unchanged'])
  self.assertEqual(before,(sha256(self.output),self.output.stat().st_mtime_ns))
 def test_invalid_replacement_preserves_published_database(self):
  self.run_import();before=sha256(self.output)
  path=self.source/SPECS['order_items'][0]
  text=path.read_text();path.write_text(text.replace('c'*32,'0'*32))
  with self.assertRaises(sqlite3.IntegrityError):self.run_import(True)
  self.assertEqual(sha256(self.output),before)
  self.assertFalse(list(self.root.glob('.olist-import-*')))
 def test_cents_precision_and_bad_headers_fail_before_publication(self):
  path=self.source/SPECS['order_items'][0]
  path.write_text(path.read_text().replace('1.00','1.001'))
  with self.assertRaisesRegex(ValueError,'exact cents'):self.run_import()
  self.assertFalse(self.output.exists())
  path.write_text(path.read_text().replace('order_item_id','invented_column'))
  with self.assertRaisesRegex(ValueError,'headers'):self.run_import()
 def test_olist_cross_grain_joins_rejected_but_safe_joins_allowed(self):
  for names in [('orders','order_items','order_payments'),('orders','order_financials','order_items'),('orders','order_reviews','order_payments')]:
   with self.assertRaisesRegex(ValueError,'mix analysis grains'):validate_join_grain(names)
  validate_join_grain(['orders','customers','order_financials'])
  validate_join_grain(['orders','products','sellers','order_items'])
 def test_does_not_replace_unowned_database(self):
  with closing(sqlite3.connect(self.output)) as db:db.execute('CREATE TABLE keep_me(x)')
  with self.assertRaisesRegex(ValueError,'not created'):self.run_import(True)
  with closing(sqlite3.connect(self.output)) as db:self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE name='keep_me'").fetchone()[0],'keep_me')

if __name__=='__main__':unittest.main()
