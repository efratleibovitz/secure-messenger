# Secure Messenger

A secure, real-time messaging REST API built with FastAPI, SQLite, and Server-Sent Events (SSE).

## How to Run

**1. Install dependencies:**
```bash
pip install -r requirements.txt
```

**2. Set up your `.env` file** (already created — but replace the JWT secret with a strong random value):
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
Paste the output as `JWT_SECRET` in `.env`.

**3. Start the server:**
```bash
uvicorn server.main:app --reload
```

**4. Open the interactive docs:**
```
http://localhost:8000/docs
```

**5. Run tests:**
```bash
pytest tests/ -v
```

---

## Project Structure

```
server/
  main.py        — app entry point, lifespan, logging
  routes.py      — all HTTP handlers
  models.py      — SQLAlchemy ORM (database tables)
  schemas.py     — Pydantic request/response shapes
  auth.py        — password hashing + JWT logic
  crypto.py      — AES-256-GCM encryption/decryption
  broadcaster.py — SSE fan-out via asyncio.Queue
client/
  client.py      — terminal chat client
tests/
  test_app.py    — full test suite
```

---

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/register` | No | Create a new account |
| POST | `/login` | No | Get a JWT token |
| POST | `/messages` | Yes | Send an encrypted message |
| GET | `/messages` | Yes | Fetch your messages (decrypted) |
| GET | `/stream` | Yes | SSE stream of real-time messages |

---

## Design Decisions

### Why bcrypt for passwords?

bcrypt is intentionally slow — hashing takes ~100ms on modern hardware. That slowness is the security feature. If an attacker steals the database, brute-forcing a single password takes years instead of seconds. Fast hash functions like SHA-256 or MD5 are completely unsuitable for passwords precisely because they are fast.

bcrypt also generates a random salt automatically on every call, so two users with the same password get different hashes. There is no way to reverse a bcrypt hash — login works by re-hashing the attempt and comparing fingerprints.

### Why AES-256-GCM and not AES-CBC?

AES-CBC provides confidentiality only — it hides the content but cannot detect tampering. AES-GCM provides both:

1. **Confidentiality** — the message content is unreadable without the key
2. **Integrity** — if anyone modifies the stored ciphertext (even a single bit), decryption raises an exception instead of silently returning garbage

GCM also requires a nonce (number used once). This server generates a fresh `os.urandom(12)` nonce for every single message, so even if Alice sends "hello" ten times, each stored blob looks completely different. Reusing a nonce with the same key would completely break GCM's security guarantees.

### Why JWT for authentication?

After login, the server issues a signed JWT token. The server never stores sessions — it verifies the token's signature on every request. This means:

- No database lookup needed to authenticate a request
- Tokens are stateless and scale horizontally
- The `exp` claim enforces automatic expiry (24 hours)

The trade-off: tokens cannot be revoked before expiry. A stolen token is valid until it expires. A production system would add a token blocklist or use short-lived tokens with refresh tokens.

### Why SSE and not WebSockets?

Server-Sent Events (SSE) is a one-way push protocol — the server pushes events to the client over a long-lived HTTP connection. WebSockets are bidirectional.

For a chat app, the client sends messages via `POST /messages` (standard HTTP) and receives them via SSE. This separation is simpler to implement, easier to proxy, and works through most firewalls and load balancers without special configuration.

The trade-off: the browser's native `EventSource` API cannot set custom headers, so it cannot send `Authorization: Bearer`. This server solves it by accepting the token as a `?token=` query parameter for SSE connections. The token appears in server access logs — a known, accepted trade-off for browser SSE clients.

### Why asyncio.Queue for SSE fan-out?

Each connected SSE client gets its own `asyncio.Queue`. When `POST /messages` is called, `broadcaster.publish()` puts the message into every registered queue simultaneously. Each SSE generator pulls from its own queue independently.

This means:
- A slow client cannot block a fast client
- Disconnected clients' queues are removed in the `finally` block — no memory leak
- The fan-out is safe because asyncio is single-threaded and cooperative — no race conditions on the subscriber list

---

## Security Notes

### bcrypt Timing Oracle / Username Enumeration

A naive login implementation returns immediately for unknown users but takes ~100ms to bcrypt-check for known users. An attacker can enumerate valid usernames by measuring response time.

This server always runs `hash_password()` even when the username is not found, so every failed login takes the same ~100ms regardless of whether the username exists. A production system would also add rate-limiting (e.g., max 5 attempts per IP per minute).

---

## Known Trade-offs and Production Gaps

| Issue | Current Behavior | Production Fix |
|-------|-----------------|----------------|
| AES key lost on restart | `os.urandom(32)` was replaced with env var — but if `.env` is lost, all stored messages are permanently unreadable | Store key in AWS KMS or a secrets manager |
| JWT cannot be revoked | Stolen token is valid for 24 hours | Add a Redis-based token blocklist, or use short-lived access tokens + refresh tokens |
| Token in SSE URL | `?token=` appears in server logs and browser history | Use cookie-based auth for browser SSE clients |
| SQLite single-file DB | Fine for development, breaks under concurrent writes | Replace with PostgreSQL for production |
| No HTTPS | Tokens and messages travel in plain text over the network | Terminate TLS at a reverse proxy (nginx, AWS ALB) |
| Broadcaster is in-memory | Only works with a single server process | Replace with Redis Pub/Sub for horizontal scaling |
