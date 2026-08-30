HTTP API around the LinkedIn profile fetcher.

POST /profile   { "url": "https://www.linkedin.com/in/<slug>/" }  -> profile JSON

Env:
  LI_AT        (required)  logged-in session cookie
  JSESSIONID   (required)  session id; csrf-token derives from it
  API_KEY      (optional)  if set, callers must send  X-API-Key: <key>
  CACHE_TTL    (optional)  seconds to cache a profile (default 3600)

Run:
  pip install fastapi uvicorn curl_cffi
  export LI_AT='...'; export JSESSIONID='ajax:...'
  uvicorn app:app --host 0.0.0.0 --port 8000
