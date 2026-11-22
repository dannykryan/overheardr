"""PKCE Spotify auth tests (offline)."""

from urllib.parse import parse_qs, urlparse

import httpx
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models import OAuthStateModel, SessionLocal, SpotifySessionModel


def test_login_creates_challenge(monkeypatch) -> None:
    monkeypatch.setattr(settings, "spotify_client_id", "test-client-id")
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/auth/spotify/login?return_to=/jobs/abc")
    assert resp.status_code == 302
    loc = resp.headers["location"]
    assert "accounts.spotify.com" in loc
    qs = parse_qs(urlparse(loc).query)
    assert qs["code_challenge_method"] == ["S256"]
    assert qs["code_challenge"][0]
    assert qs["state"][0]

    with SessionLocal() as session:
        pending = session.get(OAuthStateModel, qs["state"][0])
        assert pending is not None
        assert pending.code_verifier
        assert pending.return_to == "/jobs/abc"


def test_callback_rejects_bad_state(monkeypatch) -> None:
    monkeypatch.setattr(settings, "spotify_client_id", "test-client-id")
    client = TestClient(app)
    resp = client.get("/callback?code=fake&state=not-in-db")
    assert resp.status_code == 400


def test_token_exchange_has_no_client_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "spotify_client_id", "test-client-id")
    captured: dict = {}

    def fake_post(data: dict[str, str]) -> dict:
        captured.update(data)
        return {
            "access_token": "at",
            "refresh_token": "rt",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

    def fake_profile(_token: str, http_get=None) -> dict:
        return {"id": "user1", "display_name": "Test User"}

    from app import spotify_auth

    monkeypatch.setattr(spotify_auth, "_default_token_post", fake_post)
    monkeypatch.setattr(spotify_auth, "_fetch_profile", fake_profile)

    with SessionLocal() as session:
        session.add(
            OAuthStateModel(
                state="s1",
                code_verifier="verifier-xyz",
                return_to="/",
            )
        )
        session.commit()

    client = TestClient(app, follow_redirects=False)
    resp = client.get("/callback?code=authcode&state=s1")
    assert resp.status_code == 303
    assert "client_secret" not in captured
    assert captured.get("grant_type") == "authorization_code"
    assert captured.get("code_verifier") == "verifier-xyz"

    with SessionLocal() as session:
        row = session.get(SpotifySessionModel, 1)
        assert row and row.access_token == "at"