# MARK OS v0.2.2 — Real Quest-Scoring Director + Bigger Quest Backlog

## What changed

**`app/services/director.py`** — rewritten. `choose_direction()` now takes
an optional `open_quests` list and scores every real open quest instead of
using only static if/else rules. It weighs:

- base priority
- whether the quest is already `active`
- fit between quest difficulty and today's energy (favors easy quests on
  low-energy days, hard quests on high-energy days)
- whether the estimated time fits your free hours
- whether the quest's title/description overlaps words in today's blocker
- whether cash dropped and the quest looks income-related (lead, client,
  outreach, revenue, etc.)
- a small tie-breaker toward higher-XP quests
- whether it has a due date

It picks the highest-scoring quest as **Main Quest**, the next two as
**Side Quests**, and explains *why* in plain language. If a quest scored
negative (doesn't fit today), it's called out under **Avoid**. If there are
no open quests yet, it falls back to the original static rules — nothing
breaks on a fresh install.

**`app/main.py`** — `create_checkin()` now fetches all open (non-completed)
quests from the DB and passes them into `choose_direction()`.

**`app/database.py`** — added 8 more seed quests (AI chat endpoint, unit
tests, outreach, expense review, protect family weekend, Goals→Projects→Tasks
schema draft, weekly lesson log, portfolio update) across quick/normal/hard
difficulty. Inserted with `WHERE NOT EXISTS`, so it's **safe to run against
your live Railway database** — it won't duplicate quests or touch anything
already completed.

**`app/templates/partials/direction.html`** — Main Quest and Side Quests
now link directly to their real `/quests/{id}` page when the Director picked
an actual quest (not just fallback text).

## Install

From your real repo:

```bash
git pull
git status
```

Copy the patch over:

```bash
cp -R mark-os-v0.2.2-director-patch/app/* app/
```

Run locally to confirm nothing broke:

```bash
uvicorn app.main:app --reload
```

Test:

1. Log in, open `/quests` — you should see 10 quests instead of 2.
2. Go to Today, fill in a check-in with **low energy (1-2)** and submit —
   the Main Quest should be a `quick` difficulty quest, not a `hard` one.
3. Submit again with a **blocker** that mentions "railway" or "deploy" —
   the Main Quest should shift to the Railway deploy quest.
4. Submit with **cash lower than your last check-in** — the Main Quest
   should shift toward the outreach/lead quest.
5. Click the Main Quest heading on the direction panel — it should open
   the real quest detail page.

Then commit and push:

```bash
git add app
git commit -m "Director now scores real quests; add 8 more seed quests"
git push
```

Railway will pick up the new quests automatically on next deploy — no
manual database changes needed.
