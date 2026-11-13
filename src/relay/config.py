from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    groq_api_key: SecretStr = SecretStr("")
    groq_model: str = "openai/gpt-oss-20b"
    relay_data_dir: Path = Path("data")
    relay_runs_dir: Path = Path("runs")
    relay_ui_dir: Path = Path("web/dist")
    relay_deadline_seconds: float = Field(default=30, gt=0, le=120)
    relay_max_output_tokens: int = Field(default=1200, ge=128, le=4096)
    relay_concurrency: int = Field(default=2, ge=1, le=8)
    relay_queue_capacity: int = Field(default=8, ge=0, le=100)
    relay_queue_wait_seconds: float = Field(default=5, gt=0, le=30)
    # Local protective caps; documented defaults are not measured account entitlements.
    relay_rpm: int = Field(default=30, ge=1)
    relay_tpm: int = Field(default=8000, ge=1)
    relay_rpd: int = Field(default=1000, ge=0)
    relay_tpd: int = Field(default=200000, ge=0)
    relay_source: str = Field(default="real", pattern="^(real|stand-in)$")
    relay_simulator_port: int = Field(default=8001, ge=1024, le=65535)

    def require_key(self) -> None:
        if not self.groq_api_key.get_secret_value().strip():
            raise ValueError("Set GROQ_API_KEY in local .env; never paste the key in chat.")
