from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path

# Project root — anchor all relative paths here so behaviour does not depend on
# the process working directory (uvicorn, GitHub Actions and start.bat all differ).
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    venice_api_key: str = ""
    venice_model: str = "qwen/qwen3-235b-a22b-04-28"
    cmc_api_key: str = ""
    lunarcrush_api_key: str = ""
    brief_schedule_cron: str = "0 6 * * *"
    vault_path: str = "vault"
    github_token: str = ""
    github_repo: str = "robheat/cryptocatalyst-news"
    # Branch to publish articles to. Empty means "use the repo default branch".
    publish_branch: str = ""

    # Publishing identity — feeds canonical URLs and schema.org structured data.
    site_base_url: str = "https://cryptocatalyst.news"
    publisher_name: str = "CryptoCatalyst News"
    publisher_logo_url: str = "https://cryptocatalyst.news/logo.png"
    author_name: str = "Crypto Research Autopilot"
    author_url: str = "https://cryptocatalyst.news/about"
    disclaimer: str = (
        "This article is research commentary, not financial advice. "
        "Digital assets are volatile and you may lose capital."
    )

    model_config = {
        "env_file": str(PROJECT_ROOT / ".env"),
        "env_file_encoding": "utf-8",
    }

    @property
    def vault_dir(self) -> Path:
        path = Path(self.vault_path)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def site_url(self) -> str:
        """Base site URL without a trailing slash."""
        return self.site_base_url.rstrip("/")

    def article_url(self, slug: str) -> str:
        return f"{self.site_url}/articles/{slug}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
