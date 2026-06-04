from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path


class Settings(BaseSettings):
    venice_api_key: str = ""
    venice_model: str = "qwen/qwen3-235b-a22b-04-28"
    cmc_api_key: str = ""
    lunarcrush_api_key: str = ""
    brief_schedule_cron: str = "0 6 * * *"
    vault_path: str = "vault"
    github_token: str = ""
    github_repo: str = "robheat/cryptocatalyst-news"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def vault_dir(self) -> Path:
        return Path(self.vault_path)


@lru_cache
def get_settings() -> Settings:
    return Settings()
