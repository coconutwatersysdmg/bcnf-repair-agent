"""Offline test doubles and a deterministic task-domain baseline, never LLM evidence."""
import json
from .checker import greedy_repair
from .domain import canonical

class ScriptedClient:
    mode='SCRIPTED'
    def __init__(self,responses): self.responses=iter(responses);self.requests=[]
    def complete(self,messages,context):
        self.requests.append(json.loads(json.dumps(messages)))
        return dict(content=next(self.responses),usage={},billed_cny=0,cached=False,network_attempts=0)

class SimulatedClient:
    """First return S0, then an algorithmic repair. This measures plumbing only."""
    mode='SIMULATED'
    def complete(self,messages,context):
        task=context['task']
        ids=task['initial_keep_ids'] if context['round']==0 else greedy_repair(task)
        return dict(content=canonical({'keep_ids':ids}),usage={},billed_cny=0,cached=False,network_attempts=0)
