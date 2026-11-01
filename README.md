# PinHire Webhook

A production-quality, secure webhook API built with **Python 3.11** and **FastAPI**.

The service authenticates every request with an HMAC-SHA256 signature, enforces a
520 AED refund cap, prevents duplicate transactions via in-memory idempotency, and
answers FAQ queries in under 650 ms.

---

## Features

| Feature | Detail |
|---|---|
| **HMAC-SHA256 authentication** | Every request verified before business logic |
| **Constant-time comparison** | `hmac.compare_digest` prevents timing attacks |
| **Refund limit enforcement** | Hard cap of 520 AED – immune to prompt injection |
| **Idempotency (90 s TTL)** | Duplicate tx_ref rejected within the window |
| **Async-safe concurrency** | `asyncio.Lock` prevents race conditions |
| **FAQ engine** | Static dict lookup, no external API, <650 ms |
| **Structured JSON responses** | Consistent status/reason fields |
| **Health check** | `GET /health` for Railway liveness probes |
| **Zero secret leakage** | Keys never logged or reflected in responses |

---

## Prerequisites

- Python 3.11 or later
- pip
- Git
- A Railway account (for deployment)

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/<your-username>/pinhire-webhook.git
cd pinhire-webhook

# 2. Create and activate a virtual environment
python -m venv venv

# Windows PowerShell
.\venv\Scripts\Activate.ps1

# macOS / Linux
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Environment Variable Setup

The application reads the signing key from `PINHIRE_SEED_TOKEN`.

```bash
# Copy the example file
cp .env.example .env
```

Edit `.env` and set the real value:

```
PINHIRE_SEED_TOKEN=SEED-9268-PH-1A1E
```

> **Warning**: Never commit `.env` to Git. It is listed in `.gitignore`.

For shells without dotenv auto-loading:

```powershell
# Windows PowerShell
$env:PINHIRE_SEED_TOKEN = "SEED-9268-PH-1A1E"

# macOS / Linux
export PINHIRE_SEED_TOKEN="SEED-9268-PH-1A1E"
```

---

## Local Development

```bash
# Load .env automatically and start the dev server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`.

Interactive docs: `http://localhost:8000/docs`

---

## API Endpoints

### `GET /health`

Liveness probe. No authentication required.

**Response `200`:**
```json
{"status": "ok"}
```

---

### `POST /api/guard`

Primary webhook endpoint. All requests must carry a valid HMAC-SHA256 signature.

**Required header:**
```
x-pinhire-hmac-9268: <hex_digest>
```

**Content-Type:** `application/json`

#### Event: `refund.requested`

```json
{
  "event": "refund.requested",
  "payload": {
    "tx_ref_9268": "TXN-1001",
    "refund_aed": 250,
    "customer_message": "Please refund my payment"
  }
}
```

| Response | Status Code | Body |
|---|---|---|
| Accepted | 200 | `{"status":"processed"}` |
| Duplicate | 200 | `{"status":"duplicate"}` |
| Exceeds limit | 422 | `{"status":"rejected","reason":"refund_limit_exceeded","max_refund_aed":520}` |
| Invalid amount | 422 | `{"status":"error","reason":"invalid_amount","detail":"..."}` |
| Missing tx_ref | 400 | `{"status":"error","reason":"missing_tx_ref","detail":"..."}` |
| Bad signature | 401 | `{"status":"error","reason":"invalid_signature"}` |
| Malformed JSON | 400 | `{"status":"error","reason":"malformed_json"}` |

#### Event: `faq.query`

```json
{
  "event": "faq.query",
  "payload": {
    "question": "What is the maximum refund amount?"
  }
}
```

**Response `200`:**
```json
{
  "status": "answered",
  "answer": "The maximum permitted refund is 520 AED per transaction."
}
```

---

## HMAC Signature Generation

The signature is computed as:

```
HMAC-SHA256(key=PINHIRE_SEED_TOKEN, message=raw_request_body_bytes)
hexdigest() → lowercase hex string
```

### Python example

```python
import hashlib
import hmac
import json

SEED_TOKEN = "SEED-9268-PH-1A1E"

body = json.dumps(
    {
        "event": "refund.requested",
        "payload": {"tx_ref_9268": "TXN-1001", "refund_aed": 250},
    },
    separators=(",", ":"),  # compact – no extra whitespace
).encode()

signature = hmac.new(SEED_TOKEN.encode(), body, hashlib.sha256).hexdigest()
print(signature)
```

### curl example

```bash
BODY='{"event":"refund.requested","payload":{"tx_ref_9268":"TXN-1001","refund_aed":250}}'
SIG=$(python -c "
import hashlib, hmac, sys
body = sys.stdin.buffer.read()
print(hmac.new(b'SEED-9268-PH-1A1E', body, hashlib.sha256).hexdigest())
" <<< "$BODY")

curl -X POST http://localhost:8000/api/guard \
  -H "Content-Type: application/json" \
  -H "x-pinhire-hmac-9268: $SIG" \
  -d "$BODY"
```

---

## Testing

```bash
# Run all tests
pytest -v

# Run a specific test file
pytest tests/test_security.py -v
pytest tests/test_refunds.py -v
pytest tests/test_idempotency.py -v
pytest tests/test_faq.py -v

# Run with coverage
pytest --cov=app --cov-report=term-missing
```

The test suite covers all 16 scenarios specified in the task requirements.

---

## GitHub Setup

```bash
# Initialise and push
git init
git add .
git commit -m "feat: initial PinHire webhook implementation"
git branch -M main

# Create a repository on GitHub, then:
git remote add origin https://github.com/<your-username>/pinhire-webhook.git
git push -u origin main
```

---

## Railway Deployment

### 1. Install the Railway CLI

```bash
npm install -g @railway/cli
railway login
```

### 2. Create a new project

```bash
railway init
```

### 3. Set the environment variable

```bash
railway variables set PINHIRE_SEED_TOKEN="SEED-9268-PH-1A1E"
```

### 4. Deploy

```bash
railway up
```

Railway uses the `Procfile` to start the server:

```
web: uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

### 5. Obtain the public HTTPS URL

After deployment, Railway assigns a URL in the format:

```
https://<project-name>.up.railway.app
```

Run:

```bash
railway domain
```

Or open the Railway dashboard → your project → Settings → Domains.

### 6. Test the deployed endpoint

```bash
# Health check
curl https://<your-project>.up.railway.app/health

# Signed refund request
BODY='{"event":"refund.requested","payload":{"tx_ref_9268":"TXN-DEPLOY-001","refund_aed":100}}'
SIG=$(python -c "
import hashlib, hmac, sys
body = sys.stdin.buffer.read()
print(hmac.new(b'SEED-9268-PH-1A1E', body, hashlib.sha256).hexdigest())
" <<< "$BODY")

curl -X POST https://<your-project>.up.railway.app/api/guard \
  -H "Content-Type: application/json" \
  -H "x-pinhire-hmac-9268: $SIG" \
  -d "$BODY"
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| `RuntimeError: PINHIRE_SEED_TOKEN not set` | Missing env var | Export or set in `.env` |
| `401 invalid_signature` | Wrong key or body modification after signing | Sign the exact body you will send; use compact JSON |
| `422 refund_limit_exceeded` | Amount > 520 AED | Reduce refund amount |
| `200 duplicate` | Same `tx_ref_9268` within 90 s | Use a unique tx_ref for each transaction |
| `400 malformed_json` | Body is not valid JSON | Send a properly formatted JSON body |
| Tests fail with `RuntimeError` | `PINHIRE_SEED_TOKEN` not set in shell | `export PINHIRE_SEED_TOKEN=SEED-9268-PH-1A1E` |

---

## Known Limitations

### In-Memory Idempotency

The current implementation stores idempotency records in a process-local Python
dict protected by an `asyncio.Lock`.

**Implications:**

- **Single process only.** If you scale to multiple Uvicorn workers (`--workers N`)
  or multiple Railway instances, each process has its own store. A duplicate request
  routed to a different worker will not be detected.

- **Data lost on restart.** Restarting the process clears all records.

**Production fix:** Replace `app/idempotency.py` with a Redis-backed store using
`SET key NX PX 90000` (atomic set-if-not-exists with 90 s TTL). This works across
any number of workers and instances and survives process restarts.

```python
# Sketch of Redis-backed check_and_record
async def check_and_record(tx_ref: str) -> bool:
    result = await redis.set(f"idem:{tx_ref}", "1", nx=True, px=90_000)
    return result is None  # None → key already existed → duplicate
```

For the current single-worker Railway deployment, the in-memory implementation is
sufficient and reliable.
