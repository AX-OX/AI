"""Per-app metrics. Never label with prompts, task IDs, company IDs or errors."""
from functools import wraps
import asyncio
from time import perf_counter

from langchain_core.callbacks import BaseCallbackHandler
from prometheus_client import (
    CollectorRegistry, Counter, Gauge, Histogram, Info, ProcessCollector,
    PlatformCollector, generate_latest,
)

STAGES = {'collect', 'extract', 'assess', 'discover', 'roadmap', 'respond', 'chat_route', 'chat_answer', 'external_summary'}
TOOLS = {
    'get_company_profile', 'get_business_processes', 'get_operational_metrics',
    'get_system_inventory', 'get_project_budget', 'get_solution_catalog',
    'get_solution_candidates', 'search_docs', 'get_assessment_evidence',
    'get_document_chunks', 'index_document', 'save_assessment', 'save_extraction',
    'calculate_ax_roi', 'optimize_ax_portfolio', 'create_ax_roadmap',
    'create_ax_project', 'update_project_status', 'tavily_search',
}


class AgentMetrics:
    def __init__(self, settings):
        self.registry = CollectorRegistry()
        ProcessCollector(registry=self.registry)
        PlatformCollector(registry=self.registry)
        Info('ax_agent', 'Agent configuration; mock does not call LLM/MCP', registry=self.registry).info({
            'mode': settings.mode, 'model': settings.model or 'none',
            'llm_enabled': str(settings.mode != 'mock').lower(),
        })
        self.ready = Gauge('ax_agent_ready', 'Agent lifespan is ready', registry=self.registry)
        self.http = Counter('ax_agent_http_requests_total', 'HTTP responses', ['route', 'status'], registry=self.registry)
        self.http_time = Histogram('ax_agent_http_duration_seconds', 'HTTP latency', ['route'], registry=self.registry)
        self.executions = Counter('ax_agent_executions_total', 'Execution segments, including approval pauses and retries', ['outcome'], registry=self.registry)
        self.execution_time = Histogram('ax_agent_execution_duration_seconds', 'Execution segment time', registry=self.registry,
                                        buckets=(.01, .1, 1, 5, 15, 30, 60, 120, 300, 600))
        self.active = Gauge('ax_agent_active_executions', 'Currently running execution segments', registry=self.registry)
        self.llm = Counter('ax_agent_llm_requests_total', 'LLM attempts including retries', ['model', 'stage', 'outcome'], registry=self.registry)
        self.llm_time = Histogram('ax_agent_llm_duration_seconds', 'LLM attempt duration', ['model', 'stage'], registry=self.registry,
                                 buckets=(.1, .5, 1, 2.5, 5, 10, 20, 45, 90))
        self.tokens = Counter('ax_agent_llm_tokens_total', 'Provider-reported token usage only', ['model', 'kind'], registry=self.registry)
        self.mcp = Counter('ax_agent_tool_calls_total', 'Logical tool calls; internal retries included in duration', ['tool', 'outcome'], registry=self.registry)
        self.mcp_time = Histogram('ax_agent_tool_duration_seconds', 'Logical tool call latency', ['tool'], registry=self.registry)
        for outcome in ('DONE', 'FAILED', 'WAITING_APPROVAL', 'WAITING_CONFIRMATION', 'REJECTED', 'CANCELLED'):
            self.executions.labels(outcome)

    def render(self):
        return generate_latest(self.registry)

    def record_llm(self, model, stage, outcome, duration):
        stage = stage if stage in STAGES else 'other'
        self.llm.labels(model, stage, outcome).inc()
        self.llm_time.labels(model, stage).observe(duration)


class TokenUsageCallback(BaseCallbackHandler):
    """Structured-output chains discard usage on parsed results; read raw messages."""
    def __init__(self, metrics, model):
        self.metrics, self.model = metrics, model

    def on_llm_end(self, response, **kwargs):
        for generation in response.generations:
            # Generations for a single prompt are alternative outputs. Input usage
            # is reported once on the first message by the OpenAI chat integration.
            for item in generation:
                usage = getattr(getattr(item, 'message', None), 'usage_metadata', None)
                if usage:
                    for source, kind in (('input_tokens', 'input'), ('output_tokens', 'output')):
                        value = usage.get(source)
                        if isinstance(value, int) and value >= 0:
                            self.metrics.tokens.labels(self.model, kind).inc(value)


def instrument_tool(function):
    @wraps(function)
    async def wrapped(self, *args, **kwargs):
        metrics = getattr(self, 'metrics', None)
        if metrics is None:
            return await function(self, *args, **kwargs)
        name = 'index_document' if function.__name__ == 'index_document' else (args[2] if len(args) > 2 else kwargs.get('name'))
        name = name if name in TOOLS else 'other'
        started, outcome = perf_counter(), 'error'
        try:
            result = await function(self, *args, **kwargs)
            outcome = 'success'
            return result
        except asyncio.CancelledError:
            outcome = 'cancelled'
            raise
        finally:
            metrics.mcp.labels(name, outcome).inc()
            metrics.mcp_time.labels(name).observe(perf_counter() - started)
    return wrapped


class MetricsMiddleware:
    def __init__(self, app, metrics):
        self.app, self.metrics = app, metrics

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['path'] == '/metrics':
            return await self.app(scope, receive, send)
        started, status = perf_counter(), 500

        async def capture(message):
            nonlocal status
            if message['type'] == 'http.response.start':
                status = message['status']
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            route = getattr(scope.get('route'), 'path', 'unmatched')
            self.metrics.http.labels(route, str(status)).inc()
            self.metrics.http_time.labels(route).observe(perf_counter() - started)
