# Fit Logger

An AI-powered Progressive Web App for workout logging, progress analytics, and
adaptive workout-plan generation.

Built as a single Django project using Django Templates. There is no separate
JavaScript frontend — JavaScript is used only where the browser genuinely
requires it (dynamic set inputs, IndexedDB, offline sync, the service worker,
and chart rendering).

> **Status:** Phase 1 of 13 complete (Django foundation). This README grows with
> each phase and is finalised in Phase 13.

## Problem

Lifters forget what they lifted last session. Notes-app records are
unstructured and impossible to analyse, so it is hard to tell whether strength
or training volume is actually improving — and beginners end up following
routines with no real progression.

## Solution

Log each set in seconds, see your previous performance for an exercise the
moment you select it, and get deterministic analytics (max weight, volume,
estimated 1RM, adherence, personal records, plateau signals) that also feed an
AI planner which adapts your next plan to your measured progress.

## Technology stack

| Layer | Choice |
|---|---|
| Backend | Python 3.14, Django 6.0 |
| Frontend | Django Templates, Bootstrap 5, vanilla JavaScript |
| Database | PostgreSQL (via Django ORM) |
| Analytics | Python + pandas |
| Charts | Plotly.js (chart data prepared server-side in Python) |
| AI | OpenAI API (`gpt-4o-mini`, official Python SDK, server-side only) — see deviation note below |
| Offline | Web App Manifest, Service Worker, Cache API, IndexedDB |

## Architecture

```
Browser (PWA)  ->  Django views + templates  ->  service layer  ->  Django ORM  ->  PostgreSQL
```

Views stay thin. All business logic lives in each app's `services.py`:

- `workouts/services.py` — session and set lifecycle, previous-performance lookup
- `analytics/services.py` — every metric, computed deterministically in Python
- `ai_planner/services.py` — Claude call and persistence, with `prompts.py` and `validators.py`

The AI never calculates metrics. Python computes them and passes a summary to
the model as context.

### Deviation from the original specification

The specification named the **Anthropic Claude API**. This build uses the
**OpenAI API** (`gpt-4o-mini`) instead, because that is the key the project
owner had available.

The change is contained entirely within `ai_planner/services.py` — that module
is the only code in the project that talks to an AI provider. Prompts
(`prompts.py`), schema validation (`validators.py`), storage (`models.py`) and
every template are provider-agnostic. Swapping back to Anthropic means editing
one function, `_call_model`, and the two environment variables it reads.

Everything else in the specification is followed as written.

## Project structure

The project is organised the Django way: **one app per feature domain**, and
inside every app the same separation of concerns — data, validation, routing,
business logic and tests each in their own module. To find anything, you go to
its feature and then to the layer.

```
fitlogger/
├── manage.py
├── requirements.txt
├── .env                    # local secrets — never committed
├── .env.example
├── README.md
├── fitlogger/              # project config: settings, root urls, wsgi/asgi,
│                           # context processors, project-level tests
├── users/                  # accounts, profiles, RBAC, calorie + body metrics
├── workouts/               # exercise library, sessions, sets
├── analytics/              # metrics, progress + wellness dashboards, nutrition
├── ai_planner/             # AI-backed workout-plan generation
├── assistant/              # Joey — the RAG chatbot
├── messaging/              # trainee <-> admin conversations
├── notifications/          # in-app notifications
├── adminportal/            # the admin application (dashboard, analytics, ...)
├── templates/              # server-rendered HTML, grouped by app
├── static/                 # css / js / images
└── knowledge/              # source PDFs for the chatbot — never committed
```

Every app follows the same internal layout, so any feature is read the same way:

```
<app>/
├── models.py       # data — ORM models and their constraints
├── forms.py        # input validation (the "schema" layer)
├── views.py        # thin request handlers — HTTP in, HTTP out
├── urls.py         # routing for this feature
├── services.py     # all business logic; the only place that does real work
├── admin.py        # Django-admin registration
├── apps.py         # app config
├── migrations/     # per-change schema migrations, auto-generated
└── tests/          # tests, split by concern (a single tests.py when small)
```

Some apps add focused helper modules — `decorators.py` (RBAC), `validators.py`
and `prompts.py` (AI planner), `nutrition_data.py` (analytics) — the equivalent
of a `utils/` layer, kept next to the feature that uses them.

These are the same best-practice rules a `routers/ models/ schema/ services/
tests/` layout encodes, in Django's own idiom: routing in `urls.py`/`views.py`,
the schema layer in `forms.py`, business logic in `services.py`, migrations
per app, and tests mirroring each feature.

## Prerequisites

- Python 3.12+ (developed on 3.14)
- PostgreSQL 16+
- Git (optional but recommended)

## Setup (Windows / PowerShell)

**1. Create and activate the virtual environment**

```powershell
cd C:\Users\adith\fitlogger
python -m venv venv
.\venv\Scripts\Activate.ps1
```

If activation is blocked by execution policy:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

**2. Install dependencies**

```powershell
pip install -r requirements.txt
```

**3. Create the PostgreSQL database** (required from Phase 2 onward)

```powershell
& "C:\Program Files\PostgreSQL\17\bin\createdb.exe" -U postgres fitlogger
```

**4. Configure environment variables**

```powershell
Copy-Item .env.example .env
```

Then edit `.env` and set `DJANGO_SECRET_KEY`, `DATABASE_PASSWORD`, and
`OPENAI_API_KEY`. Generate a secret key with:

```powershell
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

**5. Run checks and start the server**

```powershell
python manage.py check
python manage.py runserver
```

Open <http://127.0.0.1:8000/>.

## Commands

```powershell
python manage.py check           # system checks
python manage.py migrate         # apply migrations       (Phase 2+)
python manage.py seed_exercises  # seed exercise library  (Phase 4+)
python manage.py createsuperuser # admin access           (Phase 2+)
python manage.py test            # run the test suite     (Phase 3+)
```

## Security notes

- No secret key, database password, or API key is committed. Everything sensitive
  is read from environment variables.
- CSRF protection stays enabled; Django session authentication is used.
- Data ownership is always resolved from `request.user`, never from a client-supplied ID.
- AI API calls (OpenAI) are server-side only. The key never reaches the browser.
