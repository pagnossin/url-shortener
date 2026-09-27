# URL Shortener

Command line tool to shorten and expand URLs, backed by MongoDB.

```bash
python -m app --minify=https://www.example.com/path?q=search
# https://myurlshortener.com/aZ3k9Qx

python -m app --expand=https://myurlshortener.com/aZ3k9Qx
# https://www.example.com/path?q=search
```

Short URLs expire after `EXPIRATION_SECONDS`. Minifying a URL that already has a valid short URL returns the same
one; once it has expired, the URL can be minified again and gets a new code. Expanding an unknown or expired short
URL prints a message on stderr and exits with code 1.

I also added a small web demo (FastAPI) on top of the same service, mostly to make it easy to try in a browser.
The CLI is still the main interface.

Live demo: _add the Render URL here_ (free plan, it takes about a minute to wake up; links expire after 60 s there).

## Running it

With Docker:

```bash
docker compose up -d --build                  # MongoDB + web demo on http://localhost:8000

docker compose run --rm app --minify=https://www.example.com/path?q=search
docker compose run --rm app --expand=http://localhost:8000/aZ3k9Qx

docker compose run --rm tests                 # full test suite against MongoDB
```

`EXPIRATION_SECONDS=30 docker compose up -d` is handy to see expiration without waiting an hour.

Without Docker you need Python 3.12+ and a MongoDB somewhere:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m app --minify=https://www.example.com/path?q=search
pytest                         # the MongoDB tests are skipped if it isn't reachable
uvicorn app.web:app --reload   # web demo
```

## Configuration

Everything comes from environment variables (see [.env.example](.env.example)) and is validated at startup, so a
typo in the config stops the process with a clear message instead of failing later.

| Variable | Default | |
| --- | --- | --- |
| `MONGO_URI` | `mongodb://localhost:27017` | |
| `MONGO_DB` | `url_shortener` | |
| `BASE_URL` | `https://myurlshortener.com` | prefix of the short URLs |
| `EXPIRATION_SECONDS` | `3600` | lifetime of a short URL |
| `CODE_LENGTH` | `7` | |
| `RETENTION_SECONDS` | `604800` | how long expired records are kept before MongoDB drops them |
| `MONGO_TIMEOUT_MS` | `3000` | time budget for every MongoDB operation |
| `MONGO_MAX_POOL_SIZE` | `50` | |
| `CACHE_MAX_ENTRIES`, `CACHE_MAX_TTL_SECONDS` | `10000`, `60` | web only, in-memory cache of resolved codes |
| `WEB_CONCURRENCY`, `WEB_MAX_REQUESTS` | `1`, `500` | web only, uvicorn workers and per-worker request limit |

Exit codes: `0` ok, `1` not found or expired, `2` invalid input, `3` storage unavailable, `4` bad configuration.

## How it works

```text
cli.py / web.py  ->  UrlShortenerService  ->  ShortUrlRepository  ->  MongoDB
                        (service.py)            (repository.py)
```

The CLI and the web app only translate input and output; the rules are in `UrlShortenerService`, which talks to a
repository interface. Tests use an in-memory repository for the unit tests and a real MongoDB for the rest.

A few decisions worth mentioning:

- **Codes** are 7 random base62 characters from `secrets` (about 3.5 trillion combinations). I preferred random
  codes over an encoded counter: they can't be enumerated and there is no shared counter to coordinate. Uniqueness
  comes from a unique index; a collision just means trying another code.
- **Same URL, same code.** One document per short URL, with an `active` flag and a unique partial index on the SHA-256
  of the URL (`active: true`). So there is at most one active code per URL even when two requests race, and expired
  records can stay in the collection. Minify first does a plain read (the common case costs no write), then an atomic
  `find_one_and_update` with upsert if it needs to create one.
- **Expiration** is checked when a code is read, so it's exact to the second. The TTL index only cleans up old records
  after the retention period; until then expand can still say "expired" instead of "not found".
- **URLs** must be http(s) with a host. Scheme and host are lowercased so `HTTPS://Example.com` and
  `https://example.com/` share a code. URLs with credentials (`https://bank.com@evil.com`) and URLs pointing at the
  shortener itself are rejected.

## Web demo and production notes

| Endpoint | |
| --- | --- |
| `POST /api/minify` | `201` new code, `200` existing one |
| `GET /api/expand?short_url=...` | `200`, `404`, or `410` once expired |
| `GET /{code}` | `307` redirect |
| `GET /healthz`, `GET /readyz` | liveness (no dependencies), readiness (pings MongoDB) |
| `GET /docs` | OpenAPI |

Since the redirect is the hot path, I tried to keep it cheap and predictable under load:

- resolved codes are cached in memory for up to a minute (a code never changes, and expiry is still checked on every
  request), and the redirect carries `Cache-Control: max-age` up to the expiry, so browsers and CDNs can absorb
  repeated clicks;
- `307` rather than `301`, otherwise browsers would keep redirecting after the link expired;
- anything that can't be a code (`/favicon.ico`, `/wp-admin`) is a 404 without hitting the database;
- MongoDB calls have a 3 s budget; errors become `503` with `Retry-After` instead of hanging requests, and uvicorn
  sheds load past `WEB_MAX_REQUESTS`;
- writes use `w=majority`, logs are one JSON line per request with a request id.

Things I'd add for real production: rate limiting at the edge, Prometheus metrics, and running index creation as a
migration step instead of at startup.

## Tests

```bash
pytest --cov      # unit + integration, coverage threshold 90%
mypy              # strict
ruff check . && ruff format --check .
```

The MongoDB tests cover the indexes, expiration and re-minify, code collisions, 64 threads minifying the same URL at
once, and check that reusing an existing code only sends a `find` to the database. CI runs all of this against a
MongoDB service container and builds the image.
