from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import requests
from requests.auth import HTTPBasicAuth

from .config import Settings
from .utils import token_hint, update_env_tokens


class AuthError(RuntimeError):
    pass


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str = ""
    token_type: str = "Bearer"
    expires_in: int | None = None
    scope: str = ""


class AconexAuth:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._token: TokenSet | None = None
        self.last_refresh_token_rotated = False
        self.last_env_updated = False

    def token_info(self, *, refresh: bool = False) -> dict[str, Any]:
        if refresh and self.settings.refresh_token:
            self.get_access_token()
        source = "none"
        token = self._token.access_token if self._token else ""
        if token:
            source = "memory"
        elif self.settings.refresh_token:
            source = "refresh_token_available"
        elif self.settings.access_token:
            source = "env_access_token_debug"
            token = self.settings.access_token
        elif self.settings.authorization_code:
            source = "authorization_code_available"
        return {
            "source": source,
            "client_id": self.settings.client_id,
            "audience": self.settings.api_audience,
            "base_url": self.settings.base_url,
            "access_token": token_hint(token),
            "has_refresh_token": bool(self.settings.refresh_token or (self._token and self._token.refresh_token)),
            "refresh_token_rotated": self.last_refresh_token_rotated,
            ".env updated": self.last_env_updated,
        }

    def get_access_token(self) -> str:
        if self._token and self._token.access_token:
            return self._token.access_token
        if self.settings.refresh_token:
            self._token = self.refresh_access_token(self.settings.refresh_token)
            return self._token.access_token
        if self.settings.access_token:
            self._token = TokenSet(access_token=self.settings.access_token)
            return self._token.access_token
        if self.settings.authorization_code:
            self._token = self.exchange_authorization_code(self.settings.authorization_code)
            return self._token.access_token
        raise AuthError("No token source configured. Set ACONEX_REFRESH_TOKEN, temporary ACONEX_ACCESS_TOKEN, or ACONEX_AUTHORIZATION_CODE.")

    def refresh_after_invalid_token(self) -> bool:
        refresh_token = ""
        if self._token and self._token.refresh_token:
            refresh_token = self._token.refresh_token
        elif self.settings.refresh_token:
            refresh_token = self.settings.refresh_token
        if not refresh_token:
            return False
        self._token = self.refresh_access_token(refresh_token)
        return True

    def build_authorization_url(self, *, redirect_uri: str | None = None, state: str | None = None) -> str:
        if not self.settings.authorization_url:
            raise AuthError("ACONEX_AUTHORIZATION_URL is empty.")
        if not self.settings.client_id:
            raise AuthError("ACONEX_CLIENT_ID is empty.")
        redirect_uri = redirect_uri or self.settings.redirect_uri
        state = self.settings.authorization_state if state is None else state
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.settings.client_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "resource": "ACONEX",
            }
        )
        separator = "&" if "?" in self.settings.authorization_url else "?"
        return f"{self.settings.authorization_url}{separator}{query}"

    def exchange_authorization_code(self, code: str | None = None, *, redirect_uri: str | None = None) -> TokenSet:
        code = code or self.settings.authorization_code
        if not code:
            raise AuthError("ACONEX_AUTHORIZATION_CODE is empty.")
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri or self.settings.redirect_uri,
            "audience": self.settings.api_audience,
        }
        return self._request_token(data)

    def refresh_access_token(self, refresh_token: str) -> TokenSet:
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "audience": self.settings.api_audience,
        }
        token = self._request_token(data)
        self._save_rotated_refresh_token(token.refresh_token, current_refresh_token=refresh_token)
        return token

    def rotation_status(self) -> dict[str, bool]:
        return {
            "refresh_token_rotated": self.last_refresh_token_rotated,
            ".env updated": self.last_env_updated,
        }

    def _request_token(self, data: dict[str, str]) -> TokenSet:
        if not self.settings.token_url:
            raise AuthError("ACONEX_TOKEN_URL is empty.")
        if not self.settings.client_id:
            raise AuthError("ACONEX_CLIENT_ID is empty.")
        if not self.settings.client_secret:
            raise AuthError("ACONEX_CLIENT_SECRET is empty.")
        token_auth_method = self.settings.token_auth_method
        if token_auth_method not in {"basic", "form"}:
            raise AuthError("ACONEX_TOKEN_AUTH_METHOD must be either 'basic' or 'form'.")
        try:
            if token_auth_method == "basic":
                response = requests.post(
                    self.settings.token_url,
                    data=data,
                    auth=HTTPBasicAuth(self.settings.client_id, self.settings.client_secret),
                    timeout=60,
                )
            else:
                form_data = {
                    **data,
                    "client_id": self.settings.client_id,
                    "client_secret": self.settings.client_secret,
                }
                response = requests.post(self.settings.token_url, data=form_data, timeout=60)
        except requests.RequestException as exc:
            raise AuthError(f"Token request failed before receiving a response: {exc}") from exc
        if not response.ok:
            preview = response.text[:300].replace("\n", " ")
            preview_lower = preview.lower()
            hint = ""
            if response.status_code == 401 and "invalid_client" in preview_lower:
                hint = (
                    " Check ACONEX_CLIENT_SECRET and ACONEX_CLIENT_ID. "
                    "If your Oracle app expects credentials in the request body, set ACONEX_TOKEN_AUTH_METHOD=form."
                )
            if "invalid_grant" in preview_lower or "already been consumed" in preview_lower:
                hint = " Run: python main.py exchange-code --listen --port 8080 --save-env"
            raise AuthError(f"Token request failed: HTTP {response.status_code} {preview}{hint}")
        payload = response.json()
        access_token = payload.get("access_token", "")
        if not access_token:
            raise AuthError("Token response did not contain access_token.")
        return TokenSet(
            access_token=access_token,
            refresh_token=payload.get("refresh_token", ""),
            token_type=payload.get("token_type", "Bearer"),
            expires_in=payload.get("expires_in"),
            scope=payload.get("scope", ""),
        )

    def _save_rotated_refresh_token(self, new_refresh_token: str, *, current_refresh_token: str) -> None:
        self.last_refresh_token_rotated = False
        self.last_env_updated = False
        if not new_refresh_token or new_refresh_token == current_refresh_token:
            return
        update_env_tokens(self.settings.root_dir / ".env", refresh_token=new_refresh_token)
        self.last_refresh_token_rotated = True
        self.last_env_updated = True
