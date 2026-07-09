# MARK OS v0.1

A personal operating system that records reality and gives one highest-leverage next action.

## What v0.1 does

- Stores Mark's long-term goals and flagship project in SQLite.
- Accepts a daily check-in: cash, expenses, free time, energy, accomplishments, blockers, and notes.
- Uses a transparent Python decision engine to choose:
  - one Main Quest;
  - two Side Quests;
  - one thing to avoid;
  - the reason behind the priority.
- Keeps a history of check-ins and directions.
- Runs locally with FastAPI, Jinja templates, HTMX, and SQLite.

## Why no AI yet?

The first milestone is to prove the feedback loop:

`Observe → Remember → Decide → Act → Review`

AI is useful only after the system has trustworthy data and clear actions. v0.1 keeps the decision logic visible, cheap, testable, and easy to improve.

## Project structure

```text
mark-os-v0.1/
├── app/
│   ├── main.py
│   ├── database.py
│   ├── services/
│   │   └── director.py
│   ├── static/
│   │   └── styles.css
│   └── templates/
│       ├── base.html
│       ├── index.html
│       ├── history.html
│       └── partials/
│           └── direction.html
├── data/
├── tests/
│   └── test_director.py
├── requirements.txt
├── run.ps1
└── README.md
```

## Run on Windows PowerShell

From the project folder:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\run.ps1
```

Then open:

```text
http://127.0.0.1:8000
```

The health endpoint is:

```text
http://127.0.0.1:8000/health
```

## Manual setup

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

## Run tests

```powershell
pytest -q
```

## First real test

1. Open the Today page.
2. Enter your actual current cash, today's expenses, available hours, energy, accomplishment, and real blocker.
3. Click **Generate My Direction**.
4. Judge the output with one question: **Would following this recommendation improve my real life today?**
5. Record the result tomorrow. That evidence drives v0.2.

## Planned roadmap

### v0.2 — Better memory
- Mark quests done/not done.
- Track project progress.
- Learn recurring blockers.
- Compare planned time with actual time.

### v0.3 — Integrations
- Google Calendar read-only.
- Gmail attention summary read-only.
- GitHub activity and project progress.

### v0.4 — AI Director
- Add an LLM only for ambiguous decisions and weekly reviews.
- Keep high-risk actions approval-only.
- Preserve transparent rules as guardrails.

## Product principle

> Maximum awareness. Strong recommendations. Controlled autonomy.
