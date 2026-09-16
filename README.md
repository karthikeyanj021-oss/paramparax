# ParamparaX

A living museum of India's cultural heritage — an AI-powered discovery platform for crafts, dances, festivals, heritage places, languages and origin stories.

## Features

- **The Six Worlds** — guided explorations across Arts & Handicrafts, Dance Forms, Culture & Festivals, Heritage Places, Languages, and Origins & Stories, organised state-by-state.
- **Heritage AI Guide** — an inline chatbot (no external AI calls) that answers questions from a built-in knowledge base plus document search, with voice responses, speech input, and chat export.
- **Favourites with account sync** — heart crafts from the catalogue; create a free username/password account and your favourites sync across devices.
- **Community gallery** — upload your heritage/craft photos (requires login).
- **Contact form** — visitor enquiries.
- **Multilingual** — English, हिंदी and తెలుగు, with a persistent language preference.
- **Polish** — dark mode, decorative sparkle canvas, live search, accessible semantics (WCAG-informed: skip-link, aria labels, focus management, contrast-safe palette).

## Authenticated user accounts

- Register/log in with a **username + password** (3–24 chars, password ≥ 6 chars).
- Passwords are hashed (PBKDF2 via Werkzeug) — never stored in plain text.
- Logging in unlocks: favourites sync, chat-history backup, and gallery uploads.
- Covered by: `/api/auth/register`, `/api/auth/login`, `/api/auth/logout`, `/api/auth/me`, `/api/favs`, `/api/chat`.

## Tech stack

- **Backend:** Flask + SQLite (`backend/`), gunicorn
- **Frontend:** vanilla HTML / CSS / JavaScript (`index.html`, `assets/`)
- **Storage:** local SQLite database (`backend/virasat.db`)

> Deployment note: Render's free tier uses an ephemeral filesystem, so the SQLite database resets on redeploys/restarts. For persistent accounts, plug in a hosted Postgres (Render Postgres / Neon / Supabase) via a `DATABASE_URL`.

## Run locally

```bash
pip install -r backend/requirements.txt
python backend/app.py
# open http://127.0.0.1:5000
```

The site is single-origin: Flask serves the static pages and the JSON API together.

## Deploy on Render

1. Create a **Web Service** from the `karthikeyanj021-oss/paramparax` repository.
2. **Root Directory:** `backend` · **Branch:** `main` · **Runtime:** Python 3
3. **Build:** `pip install -r requirements.txt`
4. **Start:** `gunicorn --bind 0.0.0.0:$PORT app:app`

Live: https://paramparax.onrender.com