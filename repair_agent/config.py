"""Explicit providers and price assumptions; never accept secret values in config."""
import json
import math
from pathlib import Path
from urllib.parse import urlparse

def defaults():
    return dict(provider='qwen',model='qwen3.7-flash-2026-07-15',
        base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
        input_price_cny=.2,output_price_cny=.8,price_checked_on='2026-10-17',
        price_source='https://help.aliyun.com/zh/model-studio/model-pricing',
        temperature=.2,max_output_tokens=2048,input_byte_cap=15000,feedback_bytes=1600,
        max_rounds=5,max_requests=1000,budget_cny=20,timeout_seconds=60,backend='bcnf',prompt_version='v1')

def validate_config(c):
    if not isinstance(c,dict) or set(c)!=set(defaults()): raise ValueError('unknown or missing config fields; secrets belong in environment only')
    if c['provider'] not in ('qwen','glm'): raise ValueError('provider must be qwen or glm')
    if not isinstance(c['model'],str) or not c['model'] or not isinstance(c['base_url'],str): raise ValueError('invalid model/url')
    url=urlparse(c['base_url']);host=url.hostname or ''
    allowed=(host=='dashscope.aliyuncs.com' or host.endswith('.cn-beijing.maas.aliyuncs.com')) if c['provider']=='qwen' else host=='open.bigmodel.cn'
    expected='/compatible-mode/v1' if c['provider']=='qwen' else '/api/paas/v4'
    if not allowed or url.scheme!='https' or url.username or url.password or url.query or url.fragment or url.port or url.path.rstrip('/')!=expected:
        raise ValueError('only supported official HTTPS Beijing/BigModel endpoints are allowed')
    for name in ('input_price_cny','output_price_cny','budget_cny','temperature','timeout_seconds'):
        value=c[name]
        if type(value) not in (int,float) or not math.isfinite(value) or value<0: raise ValueError('invalid '+name)
    if not 0<c['timeout_seconds']<=300 or c['temperature']>2: raise ValueError('invalid timeout/temperature')
    limits={'max_output_tokens':(1,8192),'input_byte_cap':(512,16000),'feedback_bytes':(64,12000),
            'max_rounds':(1,5),'max_requests':(0,1000000)}
    for name,(lo,hi) in limits.items():
        if type(c[name]) is not int or not lo<=c[name]<=hi: raise ValueError('invalid '+name)
    if c['backend'] not in ('generic','bcnf'): raise ValueError('invalid backend')
    for name in ('price_checked_on','price_source','prompt_version'):
        if not isinstance(c[name],str) or not c[name]: raise ValueError('invalid '+name)
    return c

def load_config(path=None):
    return validate_config(json.loads(Path(path).read_text(encoding='utf-8-sig')) if path else defaults())
