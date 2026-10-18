"""Transactional SQLite cache and conservative durable micro-yuan accounting."""
import json
import sqlite3
import time
from decimal import Decimal, ROUND_CEILING
from pathlib import Path

class BudgetLimit(RuntimeError): pass
class PendingRequest(RuntimeError):
    def __init__(self,message,billed_cny=0,network_attempts=0):
        self.billed_cny=billed_cny;self.network_attempts=network_attempts;super().__init__(message)

def units_for_tokens(input_tokens,output_tokens,input_price,output_price):
    # One micro-yuan = 1e-6 yuan. Prices are yuan / million tokens.
    value=Decimal(str(input_tokens))*Decimal(str(input_price))+Decimal(str(output_tokens))*Decimal(str(output_price))
    return int(value.to_integral_value(rounding=ROUND_CEILING))

class Store:
    def __init__(self,path,budget_cny,max_requests):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        self.limit=int((Decimal(str(budget_cny))*1000000).to_integral_value(rounding=ROUND_CEILING))
        self.max_requests=max_requests
        self.db=sqlite3.connect(path,timeout=15,isolation_level=None)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS requests (key TEXT PRIMARY KEY,status TEXT NOT NULL,cost_units INTEGER NOT NULL,response TEXT,created REAL NOT NULL)')

    def __enter__(self):return self
    def __exit__(self,*args):self.db.close()

    def lookup(self,key):
        row=self.db.execute('SELECT * FROM requests WHERE key=?',(key,)).fetchone()
        if row is None:return None
        obj=dict(row);obj['response']=json.loads(row['response']) if row['response'] else None
        return obj

    def reserve(self,key,cost_units):
        if type(cost_units) is not int or cost_units<0:raise ValueError('invalid reservation')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            prior=self.db.execute('SELECT status FROM requests WHERE key=?',(key,)).fetchone()
            if prior:
                if prior['status']!='done':raise PendingRequest('existing request has an uncertain outcome; no automatic retry')
                self.db.execute('COMMIT');return False
            count,total=self.db.execute('SELECT count(*),coalesce(sum(cost_units),0) FROM requests').fetchone()
            if count>=self.max_requests or total+cost_units>self.limit: raise BudgetLimit('request or cost budget reached')
            self.db.execute('INSERT INTO requests VALUES (?,?,?,?,?)',(key,'pending',cost_units,None,time.time()))
            self.db.execute('COMMIT');return True
        except BaseException:
            if self.db.in_transaction:self.db.execute('ROLLBACK')
            raise

    def finish(self,key,response,cost_units):
        if type(cost_units) is not int or cost_units<0:raise ValueError('invalid charge')
        # A larger-than-reserved charge is recorded, never hidden to make the budget look respected.
        cursor=self.db.execute('UPDATE requests SET status=?,response=?,cost_units=? WHERE key=? AND status=?',
                              ('done',json.dumps(response,ensure_ascii=False,allow_nan=False),cost_units,key,'pending'))
        if cursor.rowcount!=1:raise PendingRequest('request was not pending')

    def uncertain(self,key):
        self.db.execute('UPDATE requests SET status=? WHERE key=? AND status=?',('uncertain',key,'pending'))

    def summary(self):
        count,total,uncertain=self.db.execute("SELECT count(*),coalesce(sum(cost_units),0),coalesce(sum(status!='done'),0) FROM requests").fetchone()
        return dict(attempts=count,cost_cny=total/1000000,uncertain_requests=uncertain,
                    budget_cny=self.limit/1000000,max_requests=self.max_requests)

    def rows(self):return [dict(row) for row in self.db.execute('SELECT * FROM requests ORDER BY created')]
