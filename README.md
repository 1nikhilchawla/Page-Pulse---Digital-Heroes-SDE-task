# Page Pulse

A small web tool that audits any URL and returns a JSON health report — HTTP
status, response time, title, meta description, H1 count, images missing alt
text, and word count — plus a composite **Pulse Score** (0–100) that turns
those signals into one number, shown as a live EKG-style waveform.

Built for the Digital Heroes SDE internship qualification task.

**Live demo:** _add your deployed URL here after following [Deployment](#deployment) below_
**API docs (Swagger):** `<your-url>/docs`

---

## Why it's built this way

The task brief weights **correctness and error handling at 40%** — more than
code quality (35%) or API design (25%) combined. So the design decisions
below are mostly in service of one goal: an audit of a URL that behaves
*sensibly* no matter what URL you throw at it, including the URLs a careless
implementation would crash on.

### Architecture

```
backend/
  main.py        FastAPI app: routes, exception handlers, static file mount
  models.py       Pydantic request/response schemas (the API's public shape)
  analyzer.py     Fetches a URL and extracts the report metrics
  scoring.py      Turns metrics into the 0-100 Pulse Score
  security.py     URL validation + SSRF guard (see below)
  ratelimit.py    Per-client rate limiting for the audit endpoint
  exceptions.py   One exception class per failure mode
frontend/
  index.html, style.css, app.js   Static, no build step, no framework
tests/            31 tests: HTML parsing, scoring rubric, SSRF guard, full API
```

One FastAPI process serves both the JSON API (`/api/audit`, `/api/health`)
and the static frontend (mounted at `/`), so there's exactly one thing to
deploy.

### Error handling: one exception class per failure mode

Rather than a single `try/except Exception` around the fetch, `exceptions.py`
defines a specific class for each way this can fail — `InvalidURLError`,
`BlockedURLError`, `FetchTimeoutError`, `FetchConnectionError`,
`TooManyRedirectsError`, `ResponseTooLargeError` — each with its own HTTP
status code. `main.py` has one handler for the base class, so every one of
them turns into a clean JSON error automatically:

```json
{ "error": "timeout", "message": "The server didn't respond within 10s.", "details": {} }
```

There's also a catch-all `Exception` handler as a last resort, so even a bug
we didn't anticipate returns JSON instead of a stack trace or a dropped
connection — but landing there means a gap in the list above, not a design
choice.

**A non-2xx status code from the target site is not an error.** If you audit
a page that 404s, Page Pulse reports `http_status: 404` and a warning — that
*is* the report. The task only treats it as data, and I think that's the
right read: an audit tool that refuses to report on broken pages is less
useful than one that tells you a page is broken.

**Non-HTML responses degrade, they don't fail.** Audit a PDF, a JSON API
response, or an image, and you get back `http_status`, `response_time_ms`,
and `content_type`, with a warning explaining that HTML-only fields were
skipped — not a 500.

### Security: this endpoint fetches arbitrary user-supplied URLs

That's worth pausing on, because it's the one part of this spec most
solutions built in 3–4 hours probably don't handle: **an endpoint that fetches
whatever URL a caller gives it is a ready-made SSRF (server-side request
forgery) proxy** if you don't check what you're about to fetch first.
`http://169.254.169.254/latest/meta-data/` is cloud instance metadata.
`http://localhost:6379/` is a local Redis instance. Both look like "just a
URL" to naive validation.

`security.py` resolves the hostname and rejects it if it's private, loopback,
link-local, or reserved address space — *after* DNS resolution, not just a
string check on the hostname, so a public-looking name that resolves to a
private IP ("DNS rebinding") is still caught. It re-checks again after
following redirects, since a public URL can redirect to an internal one just
as easily as DNS can rebind to one.

That check also had to be fixed once already during testing: it originally
called Python's blocking `socket.getaddrinfo()` directly inside an async
handler, with no timeout — a slow-to-resolve hostname would have stalled the
event loop, and every other in-flight request with it, for as long as that
lookup took. It now runs through the event loop's own non-blocking resolver
wrapped in a 5-second timeout. I'm noting it here rather than pretending it
was right the first time, because that's exactly the kind of bug that's easy
to miss and is the difference "40% correctness and error handling" is
actually pricing in.

Other things a caller can't abuse this endpoint for: response bodies are
capped at 5MB (`ResponseTooLargeError`), redirect chains are capped at 5
(`TooManyRedirectsError`), and audits are rate-limited to 20/minute per
client IP (`ratelimit.py`) so it can't be turned into a free crawler against
a third party.

### The Pulse Score: a rubric you can defend in one sentence per line

A single 0–100 number is only useful if you can explain exactly what it
rewards. The rubric in `scoring.py` is deliberately simple:

| Category | Points | Rule |
|---|---|---|
| Performance | 25 | Faster response time scores higher, on thresholds roughly matching perceived-performance research (<300ms feels instant, 3s+ is where users bounce) |
| SEO | 25 | Title present (8) + right length (4); meta description present (8) + right length (5) |
| Accessibility | 25 | % of `<img>` tags with real alt text, scaled directly to 25 |
| Content | 25 | Word count (15, thin-content penalty under 300 words) + exactly one H1 (10, penalized for zero or multiple) |

For a non-HTML response, only Performance is meaningful, so the other three
are `null` in the API response and the total is Performance alone scaled to
100 — never a misleadingly low absolute number built from categories that
don't apply to a PDF.

### The interface

Page Pulse literally means "the page's vitals," so the frontend reads them
the way a cardiac monitor reads a patient's: an EKG-style waveform whose
amplitude and regularity are driven by the actual computed score (a healthy
page draws a strong, steady heartbeat; a struggling one draws something
weaker and more irregular), plus the same green/amber/red status coding
hospital monitors use for at-a-glance triage. It's a plain HTML/CSS/JS page
with no build step, so it deploys as-is with the API.

---

## Running locally

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt

uvicorn backend.main:app --reload
```

Then open `http://localhost:8000/` for the frontend, or
`http://localhost:8000/docs` for interactive API docs.

## Running the tests

```bash
pytest tests/ -v
```

31 tests, no real network calls required — outbound HTTP is mocked with
`respx`, so the suite covers the timeout/connection-error/non-HTML/4xx paths
deterministically rather than depending on a real flaky server to hit.

## API

**`POST /api/audit`**

```json
{ "url": "https://example.com" }
```

→ `200` with the full report on success, or a `4xx`/`5xx` with
`{ "error": "<code>", "message": "<human-readable>", "details": {} }` on
failure. See `/docs` for the full schema.

**`GET /api/health`** → `{ "status": "ok" }`

## Deployment

Any free-tier host that runs a Python web service works. Two are wired up:

**Render** (`render.yaml` included) — connect the GitHub repo at
[render.com](https://render.com), pick "New Web Service," and Render reads
`render.yaml` automatically. Free tier spins down when idle, so the first
request after a while will be slow to wake up — that's the host, not the app.

**Railway / Heroku-style** (`Procfile` included) — same idea, connect the
repo and deploy.

**Docker** — `docker build -t page-pulse . && docker run -p 8000:8000 page-pulse`
works anywhere that runs a container.

Whichever you use, the live URL needs the footer credit line pointing at
digitalheroesco.com — already in `frontend/index.html`, so it ships with any
of the above.

## Known limitations / what I'd do with more time

- The rate limiter is in-memory and per-process — fine for one free-tier
  instance, resets on restart, and wouldn't coordinate across multiple
  instances. A real multi-instance deployment would move it to Redis.
- No caching yet: auditing the same URL twice re-fetches it. A short TTL
  cache (30–60s) would be a courteous addition for repeated audits of the
  same page.
- No JS-rendering: pages that build their content client-side (heavy SPAs)
  will report on the server-rendered HTML only, same as any tool that
  doesn't run a headless browser. Playwright/Puppeteer would fix this at a
  real latency and complexity cost — a deliberate scope cut for a 3-4 hour
  task, not an oversight.
