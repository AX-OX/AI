from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    llm_model: str = ""
    llm_fallback_model: str = ""
    embedding_model: str = ""

    langsmith_api_key: str = ""
    langsmith_project: str = "ax-navigator"

    internal_token: str = ""
    spring_internal_url: str = "http://backend:8080/internal"
    business_mcp_url: str = "http://business-mcp:9101/mcp"
    rag_mcp_url: str = "http://rag-mcp:9102/mcp"

    postgres_user: str = "ax"
    postgres_password: str = ""
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_agent_db: str = "agent"

    # Harness 한도 (§11)
    max_agent_turns: int = 8
    task_timeout_seconds: int = 120
    max_same_tool_calls: int = 3
    tool_result_max_chars: int = 2000

    @property
    def checkpointer_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_agent_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
