"""Spotify OAuth routes."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app import spotify_auth

router = APIRouter(prefix="/auth/spotify", tags=["spotify-auth"])


class SpotifyStatusOut(BaseModel):
    connected: bool
    display_name: str | None = None


@router.get("/login")
def spotify_login(return_to: str = "/") -> RedirectResponse:
    try:
        url = spotify_auth.begin_login(return_to)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return RedirectResponse(url=url, status_code=302)


@router.get("/status", response_model=SpotifyStatusOut)
def spotify_status() -> SpotifyStatusOut:
    s = spotify_auth.session_status()
    return SpotifyStatusOut(**s)


@router.post("/logout")
def spotify_logout() -> dict[str, bool]:
    spotify_auth.logout()
    return {"ok": True}