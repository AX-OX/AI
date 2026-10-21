"""Bounded public execution trace. No raw prompts or hidden reasoning are recorded."""
from collections import OrderedDict, deque
from datetime import datetime, timezone
import re


class PublicTrace:
    def __init__(self, max_tasks=100, max_events=500):
        self.tasks = OrderedDict()
        self.max_tasks, self.max_events = max_tasks, max_events

    def add(self, task_id, node, type_, data=None):
        key = str(task_id)
        if key not in self.tasks:
            self.tasks[key] = {'sequence':0, 'events':deque(maxlen=self.max_events)}
            if len(self.tasks)>self.max_tasks: self.tasks.popitem(last=False)
        self.tasks.move_to_end(key)
        task = self.tasks[key]
        task['sequence'] += 1
        def clean(value):
            if isinstance(value, dict):
                return {k:clean(v) for k,v in value.items() if not any(s in k.lower() for s in ('api_key','authorization','internal_token','secret','password'))}
            if isinstance(value, list): return [clean(v) for v in value[:20]]
            if isinstance(value,str):
                value = re.sub(r'sk-[A-Za-z0-9_-]{10,}', '[API_KEY]', value)
                return value[:1000]
            return value
        task['events'].append({'seq':task['sequence'],'ts':datetime.now(timezone.utc).isoformat(),
                               'node':node,'type':type_,'data':clean(data or {})})

    def get(self, task_id):
        task = self.tasks.get(str(task_id))
        return list(task['events']) if task else []
