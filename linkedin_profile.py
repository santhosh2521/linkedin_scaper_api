from __future__ import annotations
import re
from linkedin_parser import parse_profile
from urllib.parse import urlparse, unquote
from curl_cffi import requests as creq

BASE = "https://www.linkedin.com/voyager/api"
RESOLVER_QID = "voyagerIdentityDashProfiles.a1a483e719b20537a256b6853cdca711"
DECORATIONS = (
    "com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-93",
    "com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-91",
    "com.linkedin.voyager.dash.deco.identity.profile.FullProfileWithEntities-35",
)


class LinkedInError(Exception):
    pass


class LinkedInProfileClient:
    def __init__(self, li_at: str, jsessionid: str, impersonate: str = "chrome"):
        csrf = jsessionid.strip('"')
        self._session = creq.Session(impersonate=impersonate)
        self._session.headers.update({
            "accept": "application/vnd.linkedin.normalized+json+2.1",
            "accept-language": "en-US,en;q=0.9",
            "csrf-token": csrf,
            "x-restli-protocol-version": "2.0.0",
            "x-li-lang": "en_US",
            "x-li-track": '{"clientVersion":"1.13.40976","mpVersion":"1.13.40976","osName":"web","timezoneOffset":5.5,"timezone":"Asia/Calcutta","deviceFormFactor":"DESKTOP","mpName":"voyager-web"}'
        })
        for name, val in {
            "li_at": li_at,
            "JSESSIONID": f'"{csrf}"',
            "lang": "v=2&lang=en-us",
            "liap": "true",
        }.items():
            self._session.cookies.set(name, val, domain=".linkedin.com")

    # ── HTTP ─────────────────────────────────────────────────────────────
    def _get(self, url: str) -> dict:
        r = self._session.get(url, allow_redirects=False, timeout=30)
        if r.status_code in (301, 302, 303, 307, 308):
            raise LinkedInError(
                f"HTTP {r.status_code} redirect — session invalid/expired or rate-limit Refresh li_at + JSESSIONID (same session), or slow down."
            )
        if r.status_code in (401, 403):
            raise LinkedInError(f"HTTP {r.status_code} — cookies invalid/expired.")
        if r.status_code == 429:
            raise LinkedInError("HTTP 429 — rate limited. Wait and retry.")
        if r.status_code >= 400:
            raise LinkedInError(f"HTTP {r.status_code}: {r.text[:200]}")
        return r.json()

    # ── Steps ────────────────────────────────────────────────────────────
    @staticmethod
    def vanity_from_url(url_or_slug: str) -> str:
        s = url_or_slug.strip()
        if "linkedin.com" in s or s.startswith("http") or "/in/" in s:
            if not s.startswith("http"):
                s = "https://" + s
            m = re.search(r"/in/([^/?#]+)", urlparse(s).path)
            if m:
                return unquote(m.group(1))
        return s.strip("/ ").split("?")[0]

    def resolve_member_id(self, vanity: str) -> str:
        url = (
            f"{BASE}/graphql?includeWebMetadata=true"
            f"&variables=(vanityName:{vanity})&queryId={RESOLVER_QID}"
        )
        data = self._get(url)
        try:
            elements = data["data"]["data"]["identityDashProfilesByMemberIdentity"]["*elements"]
            return elements[0].split("fsd_profile:")[-1]
        except (KeyError, IndexError, TypeError):
            for e in data.get("included", []):
                urn = e.get("entityUrn", "")
                if "fsd_profile:" in urn:
                    return urn.split("fsd_profile:")[-1]
        raise LinkedInError(f"Could not resolve member id for '{vanity}' (profile not found?).")

    def fetch_full(self, member_id: str) -> list[dict]:
        for deco in DECORATIONS:
            url = (
                f"{BASE}/identity/dash/profiles?q=memberIdentity"
                f"&memberIdentity={member_id}&decorationId={deco}"
            )
            try:
                data = self._get(url)
            except LinkedInError:
                continue
            inc = data.get("included", [])
            if inc:
                return inc
        raise LinkedInError("No profile data returned (all decoration versions failed")

    # ── Public API ───────────────────────────────────────────────────────
    def get_profile(self, url_or_slug: str, member_id: str | None = None) -> dict:
        vanity = self.vanity_from_url(url_or_slug)
        if member_id is None:
            member_id = self.resolve_member_id(vanity)
        included = self.fetch_full(member_id)
        result = parse_profile(included, member_id)
        result["public_identifier"] = vanity
        result["profile_url"] = f"https://www.linkedin.com/in/{vanity}/"
        return result