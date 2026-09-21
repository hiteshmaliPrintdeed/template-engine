# S3 Direct Upload — Setup & Operations

How to run Pixovo with photo bytes in S3 instead of on the backend's local disk,
and with full-resolution originals uploaded straight from the browser to the
bucket.

Local disk remains the default. Nothing here is required to run the app.

---

## 1. What changes

| | Local disk (default) | S3 |
|---|---|---|
| 512px thumbnails | written to `app/uploads/thumbnails/` | POSTed to `/api/photobook/ingest` as today, then written to the bucket by the backend |
| Full-res originals | POSTed to `/api/upload-originals` | **browser → bucket directly**, via a presigned POST |
| Export PDFs | written to `app/exports/` | written to the bucket |
| Reads | `/uploads/...` served by a `StaticFiles` mount | `/uploads/...` 307-redirects to a short-lived presigned GET |

Thumbnails deliberately keep flowing through the backend. The Phase-1 filter
engine has to decode those bytes anyway, so routing them via the bucket would
add a download per photo on the request path for no benefit. The 20 MB
originals — the ones that actually cost bandwidth and disk — never touch the
server.

**Photo URLs do not change.** `url_for()` returns the same relative
`/uploads/{key}` string in both modes. That is load-bearing rather than
cosmetic: those strings are persisted in four columns of `photos`, embedded in
`jobs.variations_json` by the solver, and read back out by
`dsa_solver.reshuffle_single_spread_engine()`. A presigned (expiring) URL in
any of those places would rot. Consequences worth knowing:

* switching modes needs **no data migration**
* the bucket can be renamed or moved by editing config only
* every image costs one extra ~300-byte redirect (halved again by
  `Cache-Control: private`)

---

## 2. Bucket setup

### Block public access

Leave S3 Block Public Access **on** and set no public-read ACL. Every read goes
through the presigned-GET redirect, so nothing needs to be public.

### CORS — required for direct upload

Without this, browser uploads fail with an opaque `TypeError: Failed to fetch`
and no status code, because the preflight never produces readable headers. The
client cannot distinguish that from being offline, which is why it gives up
after two such failures and falls back to proxy uploads for the rest of the
session (see §6).

```json
[
  {
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["POST", "PUT", "GET", "HEAD"],
    "AllowedOrigins": [
      "http://localhost:5173",
      "https://your-app-domain.example"
    ],
    "ExposeHeaders": ["ETag"],
    "MaxAgeSeconds": 3000
  }
]
```

`AllowedOrigins` must list exact origins — wildcards do not work with a
credentialed request. **If you serve the app through ngrok, that hostname
changes**, and the CORS policy has to change with it. `startup_check()` logs
the bucket's actual CORS rules at boot so a mismatch is visible before a user
hits it.

### Lifecycle rules — required

```json
{
  "Rules": [
    {
      "ID": "abort-incomplete-multipart",
      "Status": "Enabled",
      "Filter": { "Prefix": "" },
      "AbortIncompleteMultipartUpload": { "DaysAfterInitiation": 1 }
    },
    {
      "ID": "expire-originals",
      "Status": "Enabled",
      "Filter": { "Prefix": "originals/" },
      "Expiration": { "Days": 30 }
    }
  ]
}
```

The first is not optional. `upload_fileobj` on an original over 8 MB creates a
multipart upload; a killed worker leaves parts that never appear in
`list_objects_v2` but **do** appear on the invoice.

The second is a backstop: there is no retention sweep yet (see §7), so without
an expiry rule the bucket grows without bound.

### IAM

In production use an instance or task role, not keys in `.env`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"],
      "Resource": "arn:aws:s3:::YOUR_BUCKET/YOUR_PREFIX/*"
    },
    {
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::YOUR_BUCKET"
    }
  ]
}
```

Scope it tightly. Presigning performs no API call and needs no extra
permission, but **the resulting URL inherits the signer's permissions** — a
broad role mints broad presigned URLs.

With an instance role, presigned URLs are signed with temporary credentials and
carry `X-Amz-Security-Token`, so their real lifetime is
`min(TTL, token lifetime)`. At a 15-minute TTL this never matters; do not set a
multi-day TTL and expect it to work.

### NTP

The host must have accurate time. More than ~15 minutes of clock skew makes
every sigv4 call fail with `RequestTimeTooSkewed`, including every presign
handed to a browser. `startup_check()` refuses to start above 300 s of skew.
Only the *server's* clock matters — the client never signs anything, so a user
with a wrong clock is unaffected.

---

## 3. Configuration

| Variable | Default | Meaning |
|---|---|---|
| `PIXOVO_STORAGE` | `local` | `local` \| `s3`. Anything else refuses to start. |
| `PIXOVO_DIRECT_UPLOAD` | `0` | `1` enables browser→bucket uploads. Off even in S3 mode until you opt in. |
| `PIXOVO_S3_BUCKET` | — | Required when `PIXOVO_STORAGE=s3`. |
| `PIXOVO_S3_REGION` | — | Required when `PIXOVO_STORAGE=s3`. |
| `PIXOVO_S3_ENDPOINT_URL` | — | Set for MinIO / Cloudflare R2. Empty means real AWS. Also switches to path-style addressing. |
| `PIXOVO_S3_KEY_PREFIX` | — | e.g. `staging` → `staging/originals/...`. Lets environments share a bucket safely. |
| `PIXOVO_S3_PRESIGN_MODE` | `post` | `post` \| `put`. See §4. |
| `PIXOVO_S3_PRESIGN_TTL` | `900` | Upload URL lifetime, seconds. |
| `PIXOVO_S3_MEDIA_GET_TTL` | `3600` | Read URL lifetime, seconds. |
| `PIXOVO_S3_SSE` | — | `AES256` or `aws:kms`. |
| `PIXOVO_S3_SSE_KMS_KEY_ID` | — | With `aws:kms`. |
| `PIXOVO_S3_STORAGE_CLASS` | — | e.g. `INTELLIGENT_TIERING`. |
| `PIXOVO_S3_MAX_POOL` | `max(32, workers*4)` | boto3 connection pool. The default of 10 silently queues during ingest fan-out. |
| `PIXOVO_S3_STARTUP_CHECK` | `1` | `head_bucket` + clock skew + CORS probe at boot. |
| `PIXOVO_SCRATCH_DIR` | `backend/.scratch` | Staging for bytes in transit and the remote-object cache. |
| `PIXOVO_SCRATCH_MAX_BYTES` | `8 GiB` | Object-cache byte budget. |
| `PIXOVO_SCRATCH_TTL_SECONDS` | `3600` | Object-cache entry TTL. |
| `PIXOVO_SCRATCH_MIN_FREE_BYTES` | `5 GiB` | Hard free-space floor; evicts regardless of budget. |
| `PIXOVO_PRESIGN_RATE_PER_MIN` | `120` | Per-session presign rate limit. |
| `MAX_FILE_SIZE` | `20 MiB` | Per-photo ceiling. Moved here from `main.py`. |
| `GLOBAL_STORAGE_BUDGET` | `60 GiB` | Supersedes `GLOBAL_DISK_WATERMARK`, which still works as an alias. Always was a DB counter, so it is storage-agnostic; in S3 mode it is a billing guard. |

Credentials come from boto3's default chain. For dev against MinIO, put
`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` in `backend/.env`.

### Misconfiguration is fatal, on purpose

`PIXOVO_STORAGE=s3` with a missing bucket or region **refuses to boot**. It does
not fall back to local disk, because `url_for()` returns the same string in both
modes — so a silent fallback is indistinguishable in the logs, the database and
the UI. The container would start, accept uploads, write them to a layer that
vanishes on the next deploy, and the failure would surface as a customer's paid
print returning 404. Worse, a session spanning both modes has half its originals
in each place under identical URLs, which is unrecoverable without a manual
object inventory.

---

## 4. Presigned POST vs PUT

Default is **POST**, because only a POST policy can carry
`["content-length-range", 1, max]`, which makes S3 reject an oversize body
before accepting it. A presigned PUT's `Content-Length` is supplied by the
client, so signing it enforces nothing.

Use `PIXOVO_S3_PRESIGN_MODE=put` only if your provider's presigned-POST support
is incomplete (historically true of R2; MinIO supports both). In that mode
`max_bytes` comes back as `null` — the honest signal that the client's local
pre-check plus the confirm-time `head_object` are the only defences. An oversize
object is then deleted at confirm and the request 413s, so the cost is wasted
bandwidth rather than a busted quota.

---

## 5. Rollout

Do this in two steps, not one.

```bash
# Step 1 — S3 reads/writes, server still in the byte path.
PIXOVO_STORAGE=s3
PIXOVO_DIRECT_UPLOAD=0
```

This exercises the entire S3 read, write, media and export path while uploads
still flow through `/api/upload-originals`, where the size and quota
enforcement has been running for months. Watch it for a day.

```bash
# Step 2 — take the server out of the byte path.
PIXOVO_DIRECT_UPLOAD=1
```

Verify in devtools that the upload POST goes to the bucket origin and that no
image bytes hit the backend port.

### Rollback

* `PIXOVO_DIRECT_UPLOAD=0` — instant and total, no data implications. Clients
  negotiate per upload, so they revert on their next request with no redeploy.
* `PIXOVO_STORAGE=local` — instant for new sessions, but S3-era objects become
  unreachable, since `/uploads/{key}` would resolve against local disk.

---

## 6. Failure modes worth knowing

| Symptom | Cause | What happens |
|---|---|---|
| Uploads fail with no status code | Bucket CORS does not cover this origin | Client falls back to proxy uploads after 2 failures and reports it to `/api/client-metrics`. A CORS mistake is a performance regression, not an outage. |
| `403` mid-upload | Signature expired, or clock skew | Client re-presigns once rather than retrying a dead URL. |
| Confirm returns `409 object_missing` | The upload did not land | `original_synced` stays 0, so the PDF export gate keeps blocking. Client retries. |
| Confirm returns `413` | Object exceeds `MAX_FILE_SIZE` (only reachable in `put` mode) | Object is deleted, nothing is counted, client discards the file. |
| Objects in the bucket with no database row | The PUT succeeded but the confirm was lost | Self-heals: on resume the client confirms **first**, so a landed object is recognised without re-uploading. |
| Export returns `409 originals_pending` | Placed photos have no verified original yet | Expected. The client re-prioritises those uploads. |
| Scratch directory growing | Export downloads originals back from S3 | Bounded by `PIXOVO_SCRATCH_MAX_BYTES`, its TTL, and the free-space floor. |

Note that a presign expiring *during* a slow upload is not a real hazard: S3
validates the signature when it receives the request headers, so a transfer
that starts at T+890 s and takes four minutes still succeeds. The hazard is
*retrying* with a stale URL, which the client handles by re-presigning.

---

## 7. Not yet built

* **A retention sweep.** `StorageBackend.delete_prefix()` and
  `LocalObjectCache.invalidate_prefix()` exist and are tested, but nothing calls
  them in production. `sessions.status = 'expired'` is read in two places and
  never written. Until this lands, the bucket lifecycle rule in §2 is the only
  thing bounding growth.
* **An orphan reconciler.** `photos.presigned_at` is recorded so a sweep can
  find rows with `original_synced = 0 AND presigned_at < now - 15min`, `head()`
  the deterministic key, and confirm server-side.
* **CloudFront.** `url_for()` already returns a stable relative path, so putting
  a CDN in front is a change to the media route only — no data migration.

---

## 8. Local development without AWS

### Tests

`moto` provides an in-process S3, so the suite needs no credentials and no
bucket:

```bash
cd backend && python -m pytest tests/ -q
```

`tests/conftest.py` pins `PIXOVO_STORAGE=local` for the whole run, so a
developer with S3 variables exported does not run the suite against a real
bucket.

Relevant suites:

| File | Covers |
|---|---|
| `test_storage_contract.py` | One suite run against **both** backends: key validation, URL round-trip, all writes/reads, prefix-boundary isolation, concurrent writes |
| `test_direct_upload.py` | Presign authorisation, the server-chosen key, confirm accounting and replay safety |
| `test_media_route.py` | Static serving vs presigned redirect, traversal rejection |
| `test_ingest_capture_time.py` | Capture-time parity between modes — the chaptering gate |
| `test_objcache.py` | Cache eviction, single-flight, atomic publish |

### A real browser against a real endpoint

`moto` cannot prove the browser half: CORS preflight, presigned-POST form field
ordering, and `<img>` redirect following. For that, run an S3-compatible server
locally:

```bash
python -m pip install "moto[server]"
python -m moto.server -p 5055
```

Create the bucket and its CORS policy, then start the backend against it:

```bash
PIXOVO_STORAGE=s3 \
PIXOVO_DIRECT_UPLOAD=1 \
PIXOVO_S3_BUCKET=pixovo-dev \
PIXOVO_S3_REGION=us-east-1 \
PIXOVO_S3_ENDPOINT_URL=http://127.0.0.1:5055 \
AWS_ACCESS_KEY_ID=testing AWS_SECRET_ACCESS_KEY=testing \
python run.py
```

MinIO works the same way and is closer to production behaviour. In the browser's
network panel you should see, per photo:
`POST /api/uploads/presign` → `POST <bucket origin>` (201) →
`POST /api/uploads/confirm`, with no image bytes crossing the backend port.
