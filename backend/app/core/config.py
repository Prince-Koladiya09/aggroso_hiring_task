import os
from pathlib import Path
from typing import List
from pydantic import ConfigDict
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent

INSECURE_DEFAULT_SECRET = "dev-insecure-secret-key-replace-in-production-123456"


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_ENV: str = "development"
    SECRET_KEY: str = INSECURE_DEFAULT_SECRET
    DATABASE_URL: str = f"sqlite:///{BASE_DIR / 'data' / 'app.db'}"
    POLICY_PATH: str = str(BASE_DIR / "policy" / "privacy_policy_v1.yaml")
    PROMPTS_DIR: str = str(BASE_DIR / "prompts" / "v1")
    PROMPT_VERSION: str = "v1"

    # LLM
    LLM_PROVIDER: str = "mock"          # anthropic | mock
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "claude-sonnet-5-5"
    LLM_TIMEOUT_SECONDS: int = 45
    LLM_MAX_RETRIES: int = 2
    LLM_RETRY_BACKOFF_SECONDS: float = 0.5
    LLM_MAX_TOKENS: int = 2048
    FORCE_MOCK_LLM: bool = True
    SIMULATE_LLM_OUTAGE: bool = False   # S10: LLM unavailable -> deterministic fallback planner

    # Safety / demo toggles
    FAULT_INJECTION_ENABLED: bool = False
    DEMO_RESET_ENABLED: bool = True
    SHOW_TEST_ACCOUNTS: bool = True
    SEED_ON_START: bool = True

    # Caps (Tool Gateway)
    MAX_ROWS_PER_CALL: int = 100
    MAX_AGENT_TOOL_CALLS_PER_REQUEST: int = 60

    # Security
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173"
    BCRYPT_ROUNDS: int = 12
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    LOG_LEVEL: str = "INFO"
    PORT: int = 8000

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()

if settings.APP_ENV.lower() == "production" and settings.SECRET_KEY == INSECURE_DEFAULT_SECRET:
    # Fail closed: never run production with the well-known development secret.
    raise RuntimeError("SECRET_KEY must be set to a unique value when APP_ENV=production")

# Ensure data dir exists
os.makedirs(BASE_DIR / "data", exist_ok=True)
