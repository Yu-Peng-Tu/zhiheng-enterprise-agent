from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"

class Settings(BaseSettings):
    app_name: str = "知衡 · 企业知识与流程 Agent"
    database_url: str = f"sqlite:///{DATA_DIR / 'app.db'}"
    redis_url: str = ""
    llm_api_key: str = ""
    llm_base_url: str = "https://api.moonshot.cn/v1"
    llm_model: str = "kimi-k2.5"
    cors_origins: str = "http://localhost:5173,http://localhost:7100"
    debug: bool = True
    model_config = SettingsConfigDict(env_file=(ROOT / ".env", ROOT.parent / ".env"), extra="ignore")

settings = Settings()
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
