# Deployment — SiteSentinel

Two artefacts, two hosts.

| Artefact | Host | Why |
|---|---|---|
| Engine (`server.py`, `app/`, `static/`) | Cloud Run (or any container host) | needs Chromium, Lighthouse CLI, a writable disk and a multi-minute request budget |
| UI (`static/`) | Vercel | plain static files, global CDN, zero build framework |

You can also skip Vercel entirely: the engine serves the UI from the same origin, in which
case leave `SCANNER_API_ORIGIN` unset.

---

## 1. Engine → Cloud Run

```bash
export PROJECT=your-gcp-project
export REGION=asia-south1

gcloud builds submit --tag gcr.io/$PROJECT/sitesentinel

gcloud run deploy sitesentinel \
  --image gcr.io/$PROJECT/sitesentinel \
  --region $REGION \
  --allow-unauthenticated \
  --memory 2Gi --cpu 2 \
  --timeout 900 --concurrency 4 \
  --max-instances 1 --session-affinity \
  --set-env-vars GEMINI_API_KEY=your-key,SITESENTINEL_ALLOWED_ORIGINS=https://your-ui.vercel.app
```

Notes:

* `--timeout 900` — a scan runs 1–3 minutes; the default 300s is too tight on slow targets.
* `--memory 2Gi --cpu 2` — Chromium plus Lighthouse want headroom.
* `--concurrency 4` — each scan is I/O-bound but holds a browser; raise carefully.
* **SSE + Cloud Run**: streaming responses work, but the progress connection is held open
  for the whole scan, so keep `--timeout` above your slowest scan. If you front the service
  with a load balancer, make sure response buffering is off for `/api/scan/*/events`.
* Jobs and artifacts (screenshots, report.json/pdf) live in process memory and the
  container's ephemeral disk. With more than one instance, any request after the live
  stream ends — image fetches, report downloads — can land on a different instance and
  404 ("Couldn't download - No file", broken captures). Hence `--max-instances 1`
  & `--session-affinity` above. Add `--min-instances 1` if artifacts must survive
  idle scale-to-zero overnight (bills ~24/7 for one instance). Long-term, move artifacts
  to a GCS bucket or back `JobStore` with Redis/Firestore (see
  [Architecture](Architecture.md#concurrency-and-isolation)).

Sanity check:

```bash
curl -s https://YOUR-ENGINE/api/health
# {"status":"ok","model":"gemini-flash-latest","ai_enabled":true,...}
```

## 2. UI → Vercel

```bash
npm i -g vercel
vercel link                       # or: vercel --prod for a one-off
vercel env add SCANNER_API_ORIGIN production
#   → https://sitesentinel-xxxx.run.app
vercel --prod
```

`vercel.json` in the repo root already configures everything:

* `buildCommand: node scripts/build-vercel.mjs` — regenerates `static/app-config.js` with
  `window.SENTINEL_API = "<SCANNER_API_ORIGIN>"`. Leave the variable unset to get
  same-origin `/api/*` calls.
* `outputDirectory: static` — the UI ships as-is; no framework, no bundler.
* `rewrites` — everything except `/api/*` falls through to `index.html`.
* `headers` — `nosniff`, `DENY` framing, referrer policy, a locked-down permissions policy,
  and sensible cache lifetimes (`app-config.js` is always revalidated, hashed-free assets
  are cached for a day, `img/` for a week).

Then allow the UI origin on the engine:

```bash
gcloud run services update sitesentinel --region $REGION \
  --update-env-vars SITESENTINEL_ALLOWED_ORIGINS=https://your-ui.vercel.app
```

### Environment variables

| Where | Variable | Required | Purpose |
|---|---|---|---|
| Vercel | `SCANNER_API_ORIGIN` | recommended | public URL of the engine; baked into `app-config.js` at build time |
| Cloud Run | `GEMINI_API_KEY` | yes, for AI stages | drives every AI layer (`gemini-flash-latest`) |
| Cloud Run | `SITESENTINEL_ALLOWED_ORIGINS` | recommended | comma-separated CORS allow-list; defaults to `*` |
| Cloud Run | `SITESENTINEL_ALLOW_PRIVATE_TARGETS` | never in prod | dev/CI only; allows loopback/private targets |
| Cloud Run | `DEBUGBUNDLE_PROJECT_TOKEN` | optional | enables DebugBundle error capture (agent-readable incident bundles); unset = capture off |
| Cloud Run | `DEBUGBUNDLE_ENVIRONMENT` | optional | DebugBundle environment label; defaults to `production` |
| Cloud Run | `PORT` | auto | set by Cloud Run |

Never commit `GEMINI_API_KEY`. Locally it can live in `.env` (gitignored); in the cloud use
Secret Manager:

```bash
echo -n "$GEMINI_API_KEY" | gcloud secrets create gemini-key --data-file=-
gcloud run services update sitesentinel --region $REGION \
  --set-secrets GEMINI_API_KEY=gemini-key:latest
```

## 3. Local container check

```bash
docker build -t sitesentinel .
docker run --rm -p 8080:8080 -e GEMINI_API_KEY=your-key sitesentinel
curl -s localhost:8080/api/health
```

The image installs Node 22, Lighthouse (pinned), Chromium with its system libraries and the
axe-core bundle, and fails the build if `node_modules/axe-core/axe.min.js` is missing.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| UI loads, scan fails with a network error | `SCANNER_API_ORIGIN` missing or wrong; check `curl $ORIGIN/api/health` |
| Browser console shows a CORS error | engine's `SITESENTINEL_ALLOWED_ORIGINS` does not include the UI origin |
| Progress bar freezes, then "stream dropped" | proxy buffering the SSE response; disable buffering or connect to the engine directly |
| `vitals` stage shows `degraded` | Lighthouse CLI not on `PATH`; the observer fallback ran. Expected locally, not in the image |
| `ai` stage shows `degraded` | `GEMINI_API_KEY` missing/invalid |
| Scan refused: robots.txt | by design — the target disallows the scanner or robots.txt was unreachable |
| Scan refused: private address | target resolves to a private range; that is the SSRF guard |
| 404 on an artifact | the job expired (`JOB_TTL_SECONDS`, default 2h) or the instance restarted |
