from dataclasses import dataclass
import os
from pathlib import Path
from functools import lru_cache
from urllib.parse import quote
from dotenv import load_dotenv

@dataclass
class Settings:
    mode: str = 'live'
    internal_token: str = ''
    checkpoint_url: str = ''
    business_url: str = 'http://business-mcp:9101/mcp'
    rag_url: str = 'http://rag-mcp:9102/mcp'
    spring_url: str = 'http://backend:8080/internal'
    model: str = ''
    fallback_model: str = ''
    timeout: float = 120
    company_id: int = 1
    max_agent_turns: int = 8
    max_same_tool_calls: int = 3
    tool_result_max_chars: int = 2000
    task_timeout_seconds: float | None = None
    policy_file: Path = Path(__file__).resolve().parents[2] / 'AX_Navigator_AI_MVP_v3/config/ax_score_policy_v1.json'
    data_dir: Path = Path(__file__).resolve().parents[2] / 'AX_Navigator_AI_MVP_v3'

    @property
    def checkpointer_dsn(self):
        return self.checkpoint_url

    @property
    def spring_internal_url(self):
        return self.spring_url

    @property
    def business_mcp_url(self):
        return self.business_url

    @property
    def rag_mcp_url(self):
        return self.rag_url

    @classmethod
    def from_env(cls):
        load_dotenv(Path.cwd() / '.env', override=False)
        load_dotenv(Path(__file__).resolve().parents[2] / '.env', override=False)
        checkpoint_url = os.getenv('AGENT_DATABASE_URL', '')
        if not checkpoint_url and os.getenv('POSTGRES_HOST'):
            user = quote(os.getenv('POSTGRES_USER', 'ax'), safe='')
            password = quote(os.getenv('POSTGRES_PASSWORD', ''), safe='')
            host = os.environ['POSTGRES_HOST']
            port = int(os.getenv('POSTGRES_PORT', '5432'))
            database = quote(os.getenv('POSTGRES_AGENT_DB', 'agent'), safe='')
            checkpoint_url = f'postgresql://{user}:{password}@{host}:{port}/{database}'
        return cls(mode=os.getenv('AGENT_MODE', 'live'), internal_token=os.getenv('INTERNAL_TOKEN', ''),
                   checkpoint_url=checkpoint_url, business_url=os.getenv('BUSINESS_MCP_URL', cls.business_url),
                   rag_url=os.getenv('RAG_MCP_URL', cls.rag_url), spring_url=os.getenv('SPRING_INTERNAL_URL', cls.spring_url),
                   model=os.getenv('LLM_MODEL', ''), fallback_model=os.getenv('LLM_FALLBACK_MODEL', ''),
                   timeout=float(os.getenv('AGENT_TIMEOUT_SECONDS', os.getenv('TASK_TIMEOUT_SECONDS', '120'))), company_id=int(os.getenv('AGENT_COMPANY_ID', '1')),
                   max_agent_turns=int(os.getenv('MAX_AGENT_TURNS', '8')),
                   max_same_tool_calls=int(os.getenv('MAX_SAME_TOOL_CALLS', '3')),
                   tool_result_max_chars=int(os.getenv('TOOL_RESULT_MAX_CHARS', '2000')),
                   data_dir=Path(os.getenv('DATASET_DIR', str(cls.data_dir))),
                   policy_file=Path(os.getenv('AX_POLICY_FILE', str(cls.policy_file))))


@lru_cache
def get_settings():
    return Settings.from_env()
