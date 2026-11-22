"""Live Spotify search path uses PKCE user token only (no client secret)."""

from unittest.mock import MagicMock

import httpx

from app.spotify import SpotifyClient


def test_search_authorization_uses_user_access_token() -> None:
    captured: list[dict] = []

    mock_http = MagicMock(spec=httpx.Client)

    def fake_get(url, *, params=None, headers=None):
        captured.append(headers or {})
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"albums": {"items": []}}
        resp.raise_for_status = MagicMock()
        return resp

    mock_http.get.side_effect = fake_get

    client = SpotifyClient(client=mock_http, token_getter=lambda: "pkce-user-token")
    client.search('album:"Test" artist:"Band"')

    assert captured, "expected at least one Spotify search request"
    assert captured[0]["Authorization"] == "Bearer pkce-user-token"
    mock_http.post.assert_not_called()


def test_search_without_token_returns_empty_without_http() -> None:
    mock_http = MagicMock(spec=httpx.Client)
    client = SpotifyClient(client=mock_http, token_getter=lambda: None)
    hits = client.search("anything")
    assert hits == []
    mock_http.get.assert_not_called()