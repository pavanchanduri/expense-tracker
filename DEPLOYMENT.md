# Deploying Spendly to Railway

## Prerequisites

- [Railway CLI](https://docs.railway.com/guides/cli) installed (`npm i -g @railway/cli`)
- Logged in: `railway login`

## One-time setup (already done)

### 1. Add gunicorn

Railway needs a production WSGI server. Add it to `requirements.txt`:

```
gunicorn==23.0.0
```

### 2. Create a Procfile

Tell Railway how to start the app:

```
web: gunicorn app:app --bind 0.0.0.0:$PORT
```

`$PORT` is injected automatically by Railway at runtime.

### 3. Initialize the Railway project

```bash
railway init --name spendly
```

### 4. Set required environment variables

```bash
railway variables --set "SECRET_KEY=$(openssl rand -hex 32)"
```

`SECRET_KEY` is required — the app raises a `RuntimeError` at startup if it's missing.

### 5. Deploy

```bash
railway up --detach
```

### 6. Generate a public domain

```bash
railway domain
```

**Live URL:** https://spendly-production-ef7a.up.railway.app

---

## Re-deploying after changes

Just push to `master` — Railway auto-deploys on every push via the GitHub integration, or trigger manually:

```bash
railway up --detach
```

---

## Checking status and logs

```bash
# Service status
railway status

# Runtime logs
railway logs

# Build logs
railway logs --build
```

---

## Known limitations

### SQLite is ephemeral on Railway

Railway's filesystem resets on every redeploy. This means:
- The database starts fresh each time
- Users registered on Railway will be lost after a redeploy
- Only the seeded demo account (`demo@spendly.com` / `demo123`) is recreated automatically via `seed_db()`

**Workaround options:**
- Re-register your account after each deploy
- Add a [Railway Volume](https://docs.railway.com/reference/volumes) for persistent storage (mounts a disk that survives redeploys)
- Migrate to a hosted Postgres database via Railway's Postgres service

### Local users don't carry over

`expense_tracker.db` is gitignored and never uploaded. Any users or expenses created locally must be re-created on the deployed app.