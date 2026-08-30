from __future__ import annotations

import os
import time
import threading

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field
from linkedin_parser import parse_profile
from dotenv import load_dotenv
from linkedin_profile import LinkedInProfileClient, LinkedInError
load_dotenv()
# ── Config ───────────────────────────────────────────────────────────────
LI_AT = os.environ.get("LI_AT", "")
JSESSIONID = os.environ.get("JSESSIONID", "")
API_KEY = os.environ.get("API_KEY", "")           # optional
CACHE_TTL = int(os.environ.get("CACHE_TTL", "3600"))

if not LI_AT or not JSESSIONID:
    raise RuntimeError("Set LI_AT and JSESSIONID environment variables.")

app = FastAPI(title="LinkedIn Profile API", version="1.0.0")

# One shared client (keeps the curl_cffi session/cookies warm)
_client = LinkedInProfileClient(LI_AT, JSESSIONID)

# ── Thread-safe TTL caches ───────────────────────────────────────────────
_lock = threading.Lock()
_profile_cache: dict[str, tuple[float, dict]] = {}   # slug -> full profile
_id_cache: dict[str, tuple[float, str]] = {}         # slug -> member_id

CACHE_TTL = int(os.environ.get("CACHE_TTL", "3600"))   # profile data: 1h
ID_TTL = int(os.environ.get("ID_TTL", "86400"))        # slug->id: 24h


def _cache_get(store: dict, key: str, ttl: int):
    with _lock:
        hit = store.get(key)
        if hit and (time.time() - hit[0] < ttl):
            return hit[1]
        store.pop(key, None)
        return None


def _cache_put(store: dict, key: str, value) -> None:
    with _lock:
        store[key] = (time.time(), value)


def _get_member_id(slug: str) -> str:
    mid = _cache_get(_id_cache, slug, ID_TTL)
    if mid:
        return mid
    mid = _client.resolve_member_id(slug)
    _cache_put(_id_cache, slug, mid)
    return mid


# ── Schemas ──────────────────────────────────────────────────────────────
class ProfileRequest(BaseModel):
    url: str = Field(..., examples=["https://www.linkedin.com/in/xyz-test/"])


# ── Routes ───────────────────────────────────────────────────────────────
@app.get("/")
def health() -> dict:
    return {"status": "ok"}


@app.post("/profile")
def get_profile(
    body: ProfileRequest,
    x_api_key: str | None = Header(default=None),
) -> dict:
    # optional API-key guard
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key.")

    if not body.url or "linkedin.com/in/" not in body.url and "/in/" not in body.url:
        # still allow bare slugs, but reject obvious junk
        if not body.url.strip():
            raise HTTPException(status_code=400, detail="Missing 'url'.")

    slug = LinkedInProfileClient.vanity_from_url(body.url)
    cached = _cache_get(_profile_cache, slug, CACHE_TTL)
    if cached:
        return {"cached": True, **cached}

    try:
        member_id = _get_member_id(slug)
        try:
            profile = _client.get_profile(body.url, member_id=member_id)
        except LinkedInError:
            _id_cache.pop(slug, None)                 # stale id -> re-resolve once
            member_id = _get_member_id(slug)
            profile = _client.get_profile(body.url, member_id=member_id)
    except LinkedInError as e:
        msg = str(e)
        if "resolve member id" in msg or "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        if "429" in msg or "rate limit" in msg.lower():
            raise HTTPException(status_code=429, detail=msg)
        raise HTTPException(status_code=502, detail=msg)

    _cache_put(_profile_cache, slug, profile)
    return {"cached": False, **profile}
