# MARK OS v0.2 patch — Login + Life OS map

## What this patch adds

- single-user login;
- signed session cookie;
- logout;
- public `/health` endpoint only;
- hidden FastAPI docs/openapi routes;
- Level 3 display from `game_state`;
- Life OS system map;
- database foundations for memories, timeline, game state, and tasks;
- safe compatibility with the imported history database.

## 1. Back up the repository

From the repo:

```bash
cd ~/Documents/Projects/mark-os
git status
git pull
```

## 2. Copy patch files over the repo

From the extracted patch folder:

```bash
cp -R app/* ~/Documents/Projects/mark-os/app/
cp requirements.txt ~/Documents/Projects/mark-os/requirements.txt
```

## 3. Install the new dependency locally

```bash
cd ~/Documents/Projects/mark-os
source .venv/bin/activate
pip install -r requirements.txt
```

## 4. Configure local login

Use your own values; do not commit them:

```bash
export MARK_OS_USERNAME="mark"
export MARK_OS_PASSWORD="choose-your-own-password"
export MARK_OS_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
```

Run:

```bash
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## 5. Configure Railway before pushing

In Railway → `mark-os` service → Variables, add:

- `MARK_OS_USERNAME` = `mark`
- `MARK_OS_PASSWORD` = your private password
- `MARK_OS_SECRET_KEY` = a random secret generated on your Mac

Generate the secret:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Do not paste either secret into GitHub or chat.

## 6. Commit and deploy

```bash
cd ~/Documents/Projects/mark-os
git status
git diff
git add app requirements.txt
git commit -m "Add secure login and Life OS system map"
git push
```

Railway should redeploy from GitHub.

## 7. Verify

- Opening `/` while logged out redirects to `/login`.
- Correct credentials open Today.
- Wrong credentials are rejected.
- `/life-os` displays Level 3 and history/memory counts.
- `/history` still shows imported history.
- `/health` remains public.
- `POST /logout` returns to the login page.
