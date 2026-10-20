from dataclasses import dataclass
import os
from pathlib import Path

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
    policy_file: Path = Path(__file__).resolve().parents[2] / 'AX_Navigator_AI_MVP_v3/config/ax_score_policy_v1.json'
    data_dir: Path = Path(__file__).resolve().parents[2] / 'AX_Navigator_AI_MVP_v3'

    @classmethod
    def from_env(cls):
        return cls(mode=os.getenv('AGENT_MODE', 'live'), internal_token=os.getenv('INTERNAL_TOKEN', ''),
                   checkpoint_url=os.getenv('AGENT_DATABASE_URL', ''), business_url=os.getenv('BUSINESS_MCP_URL', cls.business_url),
                   rag_url=os.getenv('RAG_MCP_URL', cls.rag_url), spring_url=os.getenv('SPRING_INTERNAL_URL', cls.spring_url),
                   model=os.getenv('LLM_MODEL', ''), fallback_model=os.getenv('LLM_FALLBACK_MODEL', ''),
                   timeout=float(os.getenv('AGENT_TIMEOUT_SECONDS', '120')), company_id=int(os.getenv('AGENT_COMPANY_ID', '1')),
                   data_dir=Path(os.getenv('DATASET_DIR', str(cls.data_dir))),
                   policy_file=Path(os.getenv('AX_POLICY_FILE', str(cls.policy_file))))
