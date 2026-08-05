from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import database
from app.services.playbooks import (
    assign_playbook_to_user,
    upsert_playbook,
)
from app.services.team_users import get_primary_owner_id


def _title_from_markdown(markdown_content: str, fallback: str) -> str:
    for line in markdown_content.splitlines():
        clean = line.strip()
        if clean.startswith("# "):
            return clean[2:].strip() or fallback
    return fallback


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Import an internal Markdown playbook and assign it to a "
            "Relationship Manager account."
        )
    )
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--assign-username", required=True)
    parser.add_argument("--title", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.file.expanduser().resolve()
    if not source.is_file():
        raise SystemExit(f"Playbook file not found: {source}")

    markdown_content = source.read_text(encoding="utf-8")
    fallback_title = args.slug.replace("-", " ").title()
    title = args.title or _title_from_markdown(
        markdown_content,
        fallback_title,
    )

    database.init_db()
    with database.get_db() as db:
        user = db.execute(
            """
            SELECT id, username, role, active
            FROM users
            WHERE username = ? COLLATE NOCASE
            """,
            (args.assign_username.strip(),),
        ).fetchone()
        if user is None:
            raise SystemExit(
                "The assigned username does not exist. Create the "
                "Relationship Manager account first."
            )
        if user["role"] != "relationship_manager":
            raise SystemExit(
                "The assigned account is not a Relationship Manager."
            )
        if not user["active"]:
            raise SystemExit("The assigned account is disabled.")

        playbook = upsert_playbook(
            db,
            slug=args.slug,
            title=title,
            markdown_content=markdown_content,
            created_by_user_id=get_primary_owner_id(db),
            active=True,
        )
        assign_playbook_to_user(
            db,
            playbook_id=int(playbook["id"]),
            user_id=int(user["id"]),
        )

    print(f"Imported playbook: {playbook['title']}")
    print(f"Assigned to: {user['username']}")
    print("The Markdown source remains outside Git.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
