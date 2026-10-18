"""Qwen and GLM HTTP clients; no OpenAI service dependency or automatic retries."""
import json
import os
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError
from .budget_cache import units_for_tokens, PendingRequest
from .config import validate_config
from .domain import canonical, task_hash

class ClientError(RuntimeError):
    def __init__(self,code,billed_cny=0,network_attempts=0):
        self.code=code;self.billed_cny=billed_cny;self.network_attempts=network_attempts;super().__init__(code)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def http_transport(url,body,headers,timeout):
    request=Request(url,data=canonical(body).encode('utf-8'),headers=headers,method='POST')
    with build_opener(NoRedirect()).open(request,timeout=timeout) as response:
        data=response.read(8*1024*1024+1)
    if len(data)>8*1024*1024:raise ClientError('RESPONSE_TOO_LARGE')
    return json.loads(data)

class ModelClient:
    mode='LIVE'
    def __init__(self,config,store,transport=None):
        self.config=validate_config(config);self.store=store;self.transport=transport or http_transport

    def complete(self,messages,context):
        c=self.config
        input_bound=len(canonical(messages).encode('utf-8'))+256
        if input_bound>c['input_byte_cap']:raise ClientError('CONTEXT_LIMIT')
        body=dict(model=c['model'],messages=messages,temperature=c['temperature'],
                  max_tokens=c['max_output_tokens'],stream=False)
        if c['provider']=='qwen':body['enable_thinking']=False
        else:body['thinking']={'type':'disabled'}
        key=task_hash(dict(body=body,provider=c['provider'],url=c['base_url'],prompt_version=c['prompt_version'],
            task_hash=task_hash(context['task']),arm=context['arm'],repeat=context['repeat'],round=context['round']))
        prior=self.store.lookup(key)
        if prior:
            if prior['status']!='done':raise PendingRequest('uncertain request is not automatically repeated',prior['cost_units']/1000000,1)
            reply=dict(prior['response'])
            reply.update(cached=True,billed_cny=0,network_attempts=0,
                         attributed_cost_cny=prior['cost_units']/1000000,attributed_network_attempts=1)
            return reply
        env='DASHSCOPE_API_KEY' if c['provider']=='qwen' else 'ZAI_API_KEY'
        secret=os.environ.get(env,'').strip()
        if not secret:raise ClientError('MISSING_CREDENTIAL')
        reserve=units_for_tokens(input_bound,c['max_output_tokens'],c['input_price_cny'],c['output_price_cny'])
        if not self.store.reserve(key,reserve):return self.complete(messages,context)
        try:
            obj=self.transport(c['base_url'].rstrip('/')+'/chat/completions',body,
                               {'Content-Type':'application/json','Authorization':'Bearer '+secret},c['timeout_seconds'])
            choice=obj['choices'][0];content=choice['message']['content']
            if not isinstance(content,str):raise ValueError('invalid content')
            usage=obj.get('usage')
            valid_usage=(isinstance(usage,dict) and all(type(usage.get(n)) is int and usage[n]>=0 for n in ('prompt_tokens','completion_tokens')))
            normalized={n:usage[n] for n in ('prompt_tokens','completion_tokens')} if valid_usage else {}
            charge=units_for_tokens(normalized['prompt_tokens'],normalized['completion_tokens'],c['input_price_cny'],c['output_price_cny']) if valid_usage else reserve
            reply=dict(content=content,usage=normalized,usage_missing=not valid_usage,
                finish_reason=choice.get('finish_reason'),cached=False,billed_cny=charge/1000000,network_attempts=1,
                returned_model=obj.get('model'),system_fingerprint=obj.get('system_fingerprint'),provider_response_id=obj.get('id'))
            self.store.finish(key,reply,charge)
            return reply
        except HTTPError as exc:
            self.store.uncertain(key);raise ClientError('HTTP_'+str(exc.code),reserve/1000000,1) from None
        except ClientError as exc:
            self.store.uncertain(key);raise ClientError(exc.code,reserve/1000000,1) from None
        except (KeyError,IndexError,TypeError,ValueError):
            self.store.uncertain(key);raise ClientError('INVALID_RESPONSE',reserve/1000000,1) from None
        except Exception:
            self.store.uncertain(key);raise ClientError('NETWORK_ERROR',reserve/1000000,1) from None
