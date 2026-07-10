# MARK OS Revised Phase 4 — Quest Engine

This patch implements the revised Phase 4 definition of done:

- Create/open/start/block/unblock/abandon/complete quests.
- Store append-only progress updates with progress %, notes, session minutes, blocker reason, and timestamps.
- Track estimated time vs accumulated actual time.
- Require a completion result before XP can be awarded.
- Store optional completion evidence.
- Award immutable XP exactly once using a DB-level unique event key.
- Support crossing multiple hidden level thresholds from one large XP reward.
- Record level-up history and timeline events.
- Feed completed quests into the MARK OS life timeline.
- Keep check-in Director aware of open quests.

## Install on your Mac

From your real repo:

```bash
cd ~/Documents/Projects/mark-os
git pull
git status
```

Copy the patch files:

```bash
cp -R ~/Downloads/mark-os-v0.2.2-revised-phase4/app/* app/
cp -R ~/Downloads/mark-os-v0.2.2-revised-phase4/tests/* tests/
cp -R ~/Downloads/mark-os-v0.2.2-revised-phase4/docs/* docs/
```

Run tests:

```bash
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. pytest -q
```

Expected:

```text
9 passed
```

Run locally:

```bash
uvicorn app.main:app --reload
```

Test:

- `/quests`
- create a quest;
- open it;
- start it;
- add progress with session minutes;
- block it;
- unblock it;
- complete it with a required result and evidence;
- refresh/submit again and confirm XP is not duplicated;
- check `/history` for timeline events.

Then commit and push:

```bash
git add app tests docs
git commit -m "Complete revised Phase 4 Quest Engine"
git push
```
