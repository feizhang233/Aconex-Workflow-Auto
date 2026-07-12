from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    authorization_url: str
    token_url: str
    base_url: str
    api_audience: str
    client_id: str
    client_secret: str
    token_auth_method: str
    redirect_uri: str
    authorization_state: str
    authorization_code: str
    refresh_token: str
    access_token: str
    project_id: str
    default_mail_box: str
    page_size: int
    docflow_base_url: str
    docflow_api_key: str
    cf_access_client_id: str
    cf_access_client_secret: str
    root_dir: Path = ROOT_DIR

    @property
    def raw_dir(self) -> Path:
        return self.root_dir / "data" / "raw"

    @property
    def parsed_dir(self) -> Path:
        return self.root_dir / "data" / "parsed"

    @property
    def output_dir(self) -> Path:
        return self.root_dir / "data" / "output"


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def load_settings() -> Settings:
    load_dotenv(ROOT_DIR / ".env")
    return Settings(
        authorization_url=_get("ACONEX_AUTHORIZATION_URL"),
        token_url=_get("ACONEX_TOKEN_URL"),
        base_url=_get("ACONEX_BASE_URL", "https://eu1.aconex.com").rstrip("/"),
        api_audience=_get("ACONEX_API_AUDIENCE", "https://api.aconex.com"),
        client_id=_get("ACONEX_CLIENT_ID"),
        client_secret=_get("ACONEX_CLIENT_SECRET"),
        token_auth_method=_get("ACONEX_TOKEN_AUTH_METHOD", "basic").lower(),
        redirect_uri=_get("ACONEX_REDIRECT_URI", "http://localhost:8080/callback"),
        authorization_state=_get("ACONEX_STATE", "aconex-local-auth"),
        authorization_code=_get("ACONEX_AUTHORIZATION_CODE"),
        refresh_token=_get("ACONEX_REFRESH_TOKEN"),
        access_token=_get("ACONEX_ACCESS_TOKEN"),
        project_id=_get("ACONEX_PROJECT_ID"),
        default_mail_box=_get("ACONEX_DEFAULT_MAIL_BOX", "inbox"),
        page_size=int(_get("ACONEX_PAGE_SIZE", "250") or "250"),
        docflow_base_url=_get("DOCFLOW_BASE_URL", "https://feizhang233.com").rstrip("/"),
        docflow_api_key=_get("DOCFLOW_API_KEY"),
        cf_access_client_id=_get("CF_ACCESS_CLIENT_ID"),
        cf_access_client_secret=_get("CF_ACCESS_CLIENT_SECRET"),
    )


def ensure_directories(settings: Settings) -> None:
    for path in (
        settings.raw_dir / "mail",
        settings.raw_dir / "workflow",
        settings.parsed_dir / "mail",
        settings.parsed_dir / "workflow",
        settings.output_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
