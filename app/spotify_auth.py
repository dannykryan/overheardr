"""Spotify Authorization Code with PKCE (no client secret)."""

import base64
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.models import OAuthStateModel, SessionLocal, SpotifySessionModel

logger = logging.getLogger(__name__)

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_SCOPES = (
    "playlist-modify-private playlist-modify-public user-read-private"
)

_SESSION_ID = 1


def _code_verifier() -> str:
    return secrets.token_urlsafe(64)[:128]


def _code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def begin_login(return_to: str = "/") -> str:
    """Store PKCE verifier and return Spotify authorize URL."""
    if not settings.spotify_client_id:
        raise ValueError("SPOTIFY_CLIENT_ID is not configured")

    state = secrets.token_urlsafe(32)
    verifier = _code_verifier()
    challenge = _code_challenge(verifier)

    safe_return = return_to if return_to.startswith("/") else "/"
    with SessionLocal() as session:
        session.add(
            OAuthStateModel(state=state, code_verifier=verifier, return_to=safe_return)
        )
        session.commit()

    params = {
        "client_id": settings.spotify_client_id,
        "response_type": "code",
        "redirect_uri": settings.spotify_redirect_uri,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "state": state,
        "scope": SPOTIFY_SCOPES,
    }
    return f"{SPOTIFY_AUTH_URL}?{urlencode(params)}"


def exchange_code(
    code: str,
    state: str,
    *,
    http_post: Any | None = None,
) -> tuple[str, str | None]:
    """Validate state and exchange authorization code for tokens. Returns return_to."""
    with SessionLocal() as session:
        pending = session.get(OAuthStateModel, state)
        if not pending:
            raise ValueError("Invalid or expired OAuth state")
        verifier = pending.code_verifier
        return_to = pending.return_to
        session.delete(pending)
        session.commit()

    post = http_post or _default_token_post
    token_data = post(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.spotify_redirect_uri,
            "client_id": settings.spotify_client_id,
            "code_verifier": verifier,
        }
    )

    access = token_data["access_token"]
    refresh = token_data.get("refresh_token")
    expires_in = int(token_data.get("expires_in", 3600))
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

    profile = _fetch_profile(access, http_get=None)

    with SessionLocal() as session:
        row = session.get(SpotifySessionModel, _SESSION_ID)
        if not row:
            row = SpotifySessionModel(id=_SESSION_ID)
            session.add(row)
        row.access_token = access
        if refresh:
            row.refresh_token = refresh
        row.expires_at = expires_at
        row.display_name = profile.get("display_name")
        row.user_id = profile.get("id")
        session.commit()

    return return_to


def _default_token_post(data: dict[str, str]) -> dict[str, Any]:
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            SPOTIFY_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()


def _fetch_profile(access_token: str, http_get: Any | None = None) -> dict[str, Any]:
    if http_get:
        return http_get(access_token)
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(
            "https://api.spotify.com/v1/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()


def logout() -> None:
    with SessionLocal() as session:
        row = session.get(SpotifySessionModel, _SESSION_ID)
        if row:
            row.access_token = None
            row.refresh_token = None
            row.expires_at = None
            row.display_name = None
            row.user_id = None
            session.commit()


def session_status() -> dict[str, Any]:
    with SessionLocal() as session:
        row = session.get(SpotifySessionModel, _SESSION_ID)
        if not row or not row.access_token:
            return {"connected": False, "display_name": None}
        return {"connected": True, "display_name": row.display_name}


def get_valid_access_token(
    *,
    http_post: Any | None = None,
) -> str | None:
    with SessionLocal() as session:
        row = session.get(SpotifySessionModel, _SESSION_ID)
        if not row or not row.access_token:
            return None
        expires = row.expires_at
        if expires is not None and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires and expires <= datetime.now(timezone.utc) + timedelta(seconds=60):
            if not row.refresh_token:
                return None
            post = http_post or _default_token_post
            token_data = post(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": row.refresh_token,
                    "client_id": settings.spotify_client_id,
                }
            )
            row.access_token = token_data["access_token"]
            row.expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=int(token_data.get("expires_in", 3600))
            )
            if token_data.get("refresh_token"):
                row.refresh_token = token_data["refresh_token"]
            session.commit()
            return row.access_token
        return row.access_token


def get_user_id() -> str | None:
    with SessionLocal() as session:
        row = session.get(SpotifySessionModel, _SESSION_ID)
        return row.user_id if row else None