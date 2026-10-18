import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from test_core import task
from repair_agent.budget_cache import Store, BudgetLimit, PendingRequest
from repair_agent.model_client import ModelClient, ClientError
from repair_agent.runner import first_messages
from repair_agent.config import defaults, validate_config


class BudgetTests(unittest.TestCase):
    def test_persistent_reservation_and_unknown_requests_never_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'book.db'
            with Store(path,1,2) as db:
                db.reserve('a',400000)
                with self.assertRaises(PendingRequest): db.reserve('a',400000)
                db.finish('a',{'content':'x'},100000)
                db.reserve('b',700000)
                with self.assertRaises(BudgetLimit): db.reserve('c',1)
                self.assertEqual(db.summary()['attempts'],2)
            with Store(path,1,2) as db:
                self.assertEqual(db.lookup('a')['response']['content'],'x')
                self.assertEqual(db.summary()['cost_cny'],.8)
                with self.assertRaises(PendingRequest): db.reserve('b',1)

    def test_overspend_is_recorded_and_blocks_new_request(self):
        with tempfile.TemporaryDirectory() as temp:
            with Store(Path(temp)/'a.db',.1,10) as db:
                db.reserve('a',100)
                db.finish('a',{},200000)
                self.assertEqual(db.summary()['cost_cny'],.2)
                with self.assertRaises(BudgetLimit): db.reserve('b',1)


class ClientTests(unittest.TestCase):
    def context(self,repeat=0):return dict(task=task(),arm='B2',repeat=repeat,round=0)
    def config(self):
        c=defaults();c.update(max_requests=20,budget_cny=1);return c

    def test_cache_repeats_and_no_credentials_logged(self):
        calls=[]
        def transport(url,body,headers,timeout):
            calls.append(body)
            self.assertIn('Authorization',headers)
            return {'choices':[{'message':{'content':'{"keep_ids":["x2"]}'},'finish_reason':'stop'}],
                    'usage':{'prompt_tokens':100,'completion_tokens':20}}
        with tempfile.TemporaryDirectory() as temp:
            with Store(Path(temp)/'a.db',1,20) as db:
                client=ModelClient(self.config(),db,transport)
                with patch.dict(os.environ,{'DASHSCOPE_API_KEY':'test-secret'}):
                    first=client.complete(first_messages(task()),self.context())
                    second=client.complete(first_messages(task()),self.context())
                    third=client.complete(first_messages(task()),self.context(1))
                self.assertEqual(len(calls),2)
                self.assertFalse(first['cached']);self.assertTrue(second['cached'])
                self.assertEqual(second['billed_cny'],0)
                self.assertNotIn('test-secret',json.dumps(db.rows()))

    def test_timeout_and_http_error_have_no_secret_and_no_retry(self):
        for exception,code in [(TimeoutError('test-secret'),'NETWORK_ERROR'),
                (HTTPError('url',429,'test-secret',{},None),'HTTP_429')]:
            with tempfile.TemporaryDirectory() as temp:
                with Store(Path(temp)/'a.db',1,20) as db:
                    client=ModelClient(self.config(),db,lambda *args:(_ for _ in ()).throw(exception))
                    with patch.dict(os.environ,{'DASHSCOPE_API_KEY':'test-secret'}):
                        with self.assertRaises(ClientError) as got:client.complete(first_messages(task()),self.context())
                        self.assertEqual(got.exception.code,code)
                        self.assertNotIn('test-secret',str(got.exception))
                        with self.assertRaises(PendingRequest):client.complete(first_messages(task()),self.context())
                    self.assertEqual(db.summary()['attempts'],1)
                    self.assertGreater(db.summary()['cost_cny'],0)

    def test_missing_usage_is_cached_with_conservative_charge(self):
        transport=lambda *args:{'choices':[{'message':{'content':'{}'}}]}
        with tempfile.TemporaryDirectory() as temp:
            with Store(Path(temp)/'a.db',1,20) as db:
                with patch.dict(os.environ,{'DASHSCOPE_API_KEY':'test'}):
                    reply=ModelClient(self.config(),db,transport).complete(first_messages(task()),self.context())
                self.assertTrue(reply['usage_missing'])
                self.assertGreater(reply['billed_cny'],0)

    def test_malformed_response_retains_reservation(self):
        with tempfile.TemporaryDirectory() as temp:
            with Store(Path(temp)/'a.db',1,20) as db:
                with patch.dict(os.environ,{'DASHSCOPE_API_KEY':'test'}):
                    with self.assertRaises(ClientError):ModelClient(self.config(),db,lambda *a:{}).complete(first_messages(task()),self.context())
                self.assertEqual(db.summary()['uncertain_requests'],1)

    def test_endpoint_and_prices_validation(self):
        for update in [dict(base_url='http://localhost'),dict(base_url='https://evil.example/api'),
                       dict(input_price_cny=None),dict(output_price_cny=-1),dict(max_output_tokens=0),
                       dict(budget_cny=float('nan')),dict(api_key='secret'),dict(input_byte_cap=40000)]:
            c=self.config();c.update(update)
            with self.assertRaises(ValueError):validate_config(c)


if __name__=='__main__':unittest.main()
