from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests

from .auth import AconexAuth
from .config import Settings
from .utils import preview_text, redact_mapping, safe_slug, utc_stamp, write_json


@dataclass
class SavedResponse:
    body_path: Path
    meta_path: Path
    status_code: int
    content_type: str


class AconexClient:
    def __init__(self, settings: Settings, auth: AconexAuth):
        self.settings = settings
        self.auth = auth
        self.session = requests.Session()

    def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        accept: str | None = None,
        raw_group: str,
        label: str,
        save_raw: bool = True,
    ) -> requests.Response:
        return self.request("GET", path, params=params, accept=accept, raw_group=raw_group, label=label, save_raw=save_raw)

    def post(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        accept: str | None = None,
        content_type: str | None = None,
        raw_group: str,
        label: str,
        save_raw: bool = True,
    ) -> requests.Response:
        return self.request(
            "POST",
            path,
            params=params,
            json_body=json_body,
            accept=accept,
            content_type=content_type,
            raw_group=raw_group,
            label=label,
            save_raw=save_raw,
        )

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        accept: str | None = None,
        content_type: str | None = None,
        raw_group: str,
        label: str,
        retry_on_invalid_token: bool = True,
        save_raw: bool = True,
    ) -> requests.Response:
        url = self._url(path)
        headers = {
            "Authorization": f"Bearer {self.auth.get_access_token()}",
            "Accept": accept or "*/*",
        }
        if content_type:
            headers["Content-Type"] = content_type
        response = self.session.request(method, url, params=params, json=json_body, headers=headers, timeout=120)
        if save_raw:
            saved = self.save_response(response, raw_group=raw_group, label=label, request_meta={"method": method, "url": response.url, "params": params or {}})
            self.log_response(method, response, saved)
        else:
            self.log_response(method, response, None)
        if retry_on_invalid_token and self._looks_invalid_token(response) and self.auth.refresh_after_invalid_token():
            print("Access token was rejected; refreshed token and retrying once.")
            return self.request(
                method,
                path,
                params=params,
                json_body=json_body,
                accept=accept,
                content_type=content_type,
                raw_group=raw_group,
                label=f"{label}_retry",
                retry_on_invalid_token=False,
                save_raw=save_raw,
            )
        response.raise_for_status()
        return response

    def save_response(self, response: requests.Response, *, raw_group: str, label: str, request_meta: dict[str, Any]) -> SavedResponse:
        content_type = response.headers.get("content-type", "")
        ext = self._extension(content_type)
        directory = self.settings.raw_dir / raw_group
        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{utc_stamp()}_{safe_slug(label)}_{response.status_code}"
        body_path = directory / f"{stem}.{ext}"
        meta_path = directory / f"{stem}.meta.json"
        body_path.write_bytes(response.content)
        write_json(
            meta_path,
            {
                "request": redact_mapping(request_meta),
                "response": {
                    "status_code": response.status_code,
                    "url": response.url,
                    "content_type": content_type,
                    "headers": redact_mapping(dict(response.headers)),
                    "preview": preview_text(response.content),
                    "body_path": str(body_path),
                },
            },
        )
        return SavedResponse(body_path=body_path, meta_path=meta_path, status_code=response.status_code, content_type=content_type)

    def log_response(self, method: str, response: requests.Response, saved: SavedResponse | None) -> None:
        content_type = response.headers.get("content-type", "")
        suffix = f" | saved {saved.body_path}" if saved else ""
        print(f"{method} {response.url} -> {response.status_code} {content_type or '<no content-type>'} | {preview_text(response.content)}{suffix}")

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return urljoin(f"{self.settings.base_url}/", path.lstrip("/"))

    @staticmethod
    def _extension(content_type: str) -> str:
        value = content_type.lower()
        if "json" in value:
            return "json"
        if "xml" in value:
            return "xml"
        if "zip" in value:
            return "zip"
        if "pdf" in value:
            return "pdf"
        if "text" in value:
            return "txt"
        return "bin"

    @staticmethod
    def _looks_invalid_token(response: requests.Response) -> bool:
        if response.status_code not in {401, 403}:
            return False
        text = response.text[:1000].upper()
        auth_header = response.headers.get("www-authenticate", "").upper()
        return "INVALID_TOKEN" in text or "INVALID_TOKEN" in auth_header or "EXPIRED" in text
