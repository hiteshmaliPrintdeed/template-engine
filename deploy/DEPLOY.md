# Demo deployment — Amazon Linux 2023 + Nginx + Let's Encrypt

Target: `https://storymode.pixovo.com` (UI) and `https://apistorymode.pixovo.com` (API).

## The one design decision everything follows from

The frontend has **no API base URL**. All ~15 fetch calls across 5 files use
relative paths (`/api/...`, `/uploads/...`, `/exports/...`) — see
`frontend/.env.example`, which documents this as deliberate. So the SPA must be
served from the same origin as the API.

Therefore Nginx on `storymode.pixovo.com` serves the SPA at `/` **and** proxies
`/api`, `/uploads`, `/exports` to the backend on loopback. Every request the
browser makes is same-origin, so **no CORS preflight is ever generated** — the
error class is removed structurally, not configured around.
`apistorymode.pixovo.com` is a second vhost onto the same backend for Swagger
and curl; the SPA never uses it.

The only genuine cross-origin request in the whole system is the direct browser
→ S3 upload (step 5).

---

## 0. Find free ports

```bash
sudo ss -tulpn | sort -t: -k2 -n              # everything listening, with owners
sudo ss -tulpn | grep -E ':(80|443|8001|8413)\b' || echo "all free"
```

Defaults used here: **8001** backend, **8413** SPA. 8001 is commonly taken —
confirm before committing, and substitute consistently in `backend/.env`,
`frontend/.env` and `deploy/nginx-pixovo.conf` if you change it.

Both bind to `127.0.0.1`. In the EC2 security group open **only 80 and 443**.

## 1. DNS

A records for both names → the server's public IP. Certbot's HTTP-01 challenge
fails if this has not propagated:

```bash
dig +short storymode.pixovo.com apistorymode.pixovo.com
```

## 2. Install

```bash
sudo dnf install -y nginx git python3.11 python3.11-pip mesa-libGL glib2 nodejs20
```

`mesa-libGL` + `glib2` are the Amazon Linux names for `libgl1` /
`libglib2.0-0`; `opencv-python-headless` will not import without them. Use
Python **3.11** — that is what CI validates, and mediapipe/onnxruntime wheel
availability is the real constraint.

```bash
sudo mkdir -p /srv/pixovo && sudo chown $USER:$USER /srv/pixovo
git clone <repo-url> /srv/pixovo
cd /srv/pixovo
python3.11 -m venv backend/venv
backend/venv/bin/pip install -r backend/requirements.txt
mkdir -p data/uploads data/exports data/scratch
cd frontend && npm ci && npm run build
```

## 3. Environment

`/srv/pixovo/backend/.env` — `chmod 600`, it holds the Gemini key:

```ini
GEMINI_API_KEY=...
PIXOVO_HOST=127.0.0.1
PIXOVO_PORT=8001
PIXOVO_RELOAD=0
PIXOVO_ALLOWED_ORIGINS=https://storymode.pixovo.com,https://apistorymode.pixovo.com

PIXOVO_STORAGE=s3
PIXOVO_DIRECT_UPLOAD=1
PIXOVO_S3_BUCKET=...
PIXOVO_S3_REGION=ap-south-1
PIXOVO_S3_PRESIGN_MODE=post

PIXOVO_UPLOADS_DIR=/srv/pixovo/data/uploads
PIXOVO_EXPORTS_DIR=/srv/pixovo/data/exports
PIXOVO_SCRATCH_DIR=/srv/pixovo/data/scratch
PIXOVO_DB_PATH=/srv/pixovo/data/pixovo_session.db
MAX_PHOTOS_PER_SESSION=1000
```

Prefer an EC2 instance role over `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` —
boto3 picks it up automatically. Use `PIXOVO_STORAGE=local` if S3 is not ready;
note S3 misconfiguration **raises at import** by design, so a wrong bucket fails
the boot loudly rather than degrading silently.

`/srv/pixovo/frontend/.env`:

```ini
PIXOVO_PREVIEW_PORT=8413
PIXOVO_PREVIEW_HOST=127.0.0.1
PIXOVO_PREVIEW_ALLOWED_HOSTS=storymode.pixovo.com
```

## 4. S3 bucket CORS — only if `PIXOVO_DIRECT_UPLOAD=1`

The browser POSTs/PUTs straight to S3 (`frontend/src/utils/uploadTransport.js`).
Wildcards do not work for these, so list the origin exactly:

```json
[{ "AllowedHeaders": ["*"],
   "AllowedMethods": ["POST", "PUT", "GET", "HEAD"],
   "AllowedOrigins": ["https://storymode.pixovo.com"],
   "ExposeHeaders": ["ETag"],
   "MaxAgeSeconds": 3000 }]
```

The backend reads the bucket CORS at boot and warns if it is missing — check
`journalctl -u pixovo-api`. Also add the lifecycle rules `docs/S3_SETUP.md`
calls mandatory (abort incomplete multipart after 1 day; expire `originals/`
after 30 days): no retention sweep exists in code.

**If S3 CORS misbehaves mid-demo**, the instant rollback is
`PIXOVO_DIRECT_UPLOAD=0` + `systemctl restart pixovo-api`. `/api/uploads/presign`
then returns `mode:"proxy"` and uploads route through the backend, same-origin.

## 5. Services

```bash
sudo cp /srv/pixovo/deploy/pixovo-api.service /srv/pixovo/deploy/pixovo-web.service \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pixovo-api pixovo-web
systemctl status pixovo-api pixovo-web
```

Edit `User=` in both units if you are not `ec2-user`. Do **not** add
`--workers`: the rate limiter, TTL caches and background job runner are all
in-process state.

## 6. Nginx

```bash
sudo cp /srv/pixovo/deploy/nginx-pixovo.conf /etc/nginx/conf.d/pixovo.conf
sudo nginx -t && sudo systemctl enable --now nginx
```

If 80/443 are already held by another web server, do not install a second one —
merge these two `server` blocks into the existing config.

502 with a permission denial in `/var/log/audit/audit.log` means SELinux:
`sudo setsebool -P httpd_can_network_connect 1`.

## 7. HTTPS

```bash
sudo dnf install -y certbot python3-certbot-nginx
sudo certbot --nginx -d storymode.pixovo.com -d apistorymode.pixovo.com --redirect
sudo systemctl enable --now certbot-renew.timer
```

`--redirect` installs the 80→443 redirect. This matters beyond tidiness: an
HTTPS page cannot fetch HTTP sub-resources, so mixed content would break every
API call. Because the SPA uses relative paths its requests inherit `https://`
automatically — there is no scheme left to misconfigure.

---

## Verify

```bash
sudo ss -tulpn | grep -E '8001|8413'          # both on 127.0.0.1, NOT 0.0.0.0
curl -sI https://apistorymode.pixovo.com/api/stats   # 200, valid cert
curl -sI http://storymode.pixovo.com                 # 301 -> https
sudo certbot renew --dry-run
```

Then in a browser at `https://storymode.pixovo.com`, DevTools → Network:

- **zero** `OPTIONS` preflights against the app's own origin (this is the proof
  the same-origin design is working)
- zero mixed-content warnings
- full path: create session → upload a batch → generate → job polls to
  completion → export PDF and confirm the download resolves
- refresh mid-session → rehydrates via `GET /api/sessions/{id}`, not 404/410

`journalctl -u pixovo-api -f` during an upload: no S3 CORS warning at boot, no
clock-skew failure (boot fails past 300 s skew; check `chronyc tracking`).

## Redeploy

```bash
cd /srv/pixovo && git pull
backend/venv/bin/pip install -r backend/requirements.txt
cd frontend && npm ci && npm run build
sudo systemctl restart pixovo-api pixovo-web
```

In-flight jobs are lost on restart (`BackgroundTasks` is in-process); session
state survives in SQLite. Avoid redeploying mid-demo.

## Known limits of this demo

- **No authentication.** Anyone can create a session, and anyone holding a
  `session_id` can read it. Acceptable for a demo; not for real customer photos.
- **Single worker + SQLite** caps concurrency near the tested 15 users / 1000
  photos. Scaling out requires moving the rate limiter and caches to Redis first.
