from __future__ import annotations

import ast
import shutil
from pathlib import Path


REPO_ROOT = Path.cwd()
PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def copy_payload(relative_path: str) -> None:
    source = PACKAGE_ROOT / relative_path
    destination = REPO_ROOT / relative_path
    if not source.exists():
        raise SystemExit(f"M10 payload is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == destination.resolve():
        return
    shutil.copy2(source, destination)


def parse(path: Path) -> ast.Module:
    text = path.read_text(encoding="utf-8")
    try:
        return ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        raise SystemExit(f"Cannot patch {path}: {exc}") from exc


def replace_function(
    path: Path,
    function_name: str,
    replacement: str,
) -> None:
    text = path.read_text(encoding="utf-8")
    tree = parse(path)
    target = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        ),
        None,
    )
    if target is None or not hasattr(target, "end_lineno"):
        raise SystemExit(f"Could not find {function_name}() in {path}.")
    lines = text.splitlines()
    lines[target.lineno - 1 : int(target.end_lineno)] = (
        replacement.rstrip().splitlines()
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    parse(path)


# ---------------------------------------------------------------------------
# Copy the final M10 replacement/new files.
# ---------------------------------------------------------------------------
for payload in (
    "app/db/family_workspace.py",
    "app/routes/family.py",
    "app/services/access_control.py",
    "app/templates/family_setup.html",
    "tests/test_family_workspace_release.py",
):
    copy_payload(payload)


# ---------------------------------------------------------------------------
# Ordered startup migration pipeline.
# ---------------------------------------------------------------------------
migrations_path = REPO_ROOT / "app/db/migrations.py"
migrations = migrations_path.read_text(encoding="utf-8")

if "family_workspace" not in migrations:
    if "from app.db import (" in migrations:
        anchor = "    family_ownership,\n"
        if anchor in migrations:
            migrations = migrations.replace(
                anchor,
                anchor + "    family_workspace,\n",
                1,
            )
        else:
            opening = "from app.db import (\n"
            migrations = migrations.replace(
                opening,
                opening + "    family_workspace,\n",
                1,
            )
    else:
        import_line = next(
            (
                line
                for line in migrations.splitlines()
                if line.startswith("from app.db import ")
            ),
            None,
        )
        if import_line is None:
            raise SystemExit(
                "Could not find the app.db import in migrations.py."
            )
        imported = import_line.removeprefix("from app.db import ")
        migrations = migrations.replace(
            import_line,
            f"from app.db import {imported}, family_workspace",
            1,
        )

lines = migrations.splitlines()
managed_calls = {
    "family_workspace.migrate(db)",
    "family_workspace.ensure_all_workspaces(db)",
    "family_workspace.validate(db)",
}
lines = [line for line in lines if line.strip() not in managed_calls]

backfill_index = next(
    (
        index
        for index, line in enumerate(lines)
        if line.strip() == "family_ownership.backfill_owner(db)"
    ),
    None,
)
if backfill_index is None:
    raise SystemExit(
        "Could not find family_ownership.backfill_owner(db)."
    )
indent = lines[backfill_index][
    : len(lines[backfill_index]) - len(lines[backfill_index].lstrip())
]
lines[backfill_index + 1 : backfill_index + 1] = [
    f"{indent}family_workspace.migrate(db)",
    f"{indent}family_workspace.ensure_all_workspaces(db)",
]

ownership_validate_index = next(
    (
        index
        for index, line in enumerate(lines)
        if line.strip() == "family_ownership.validate(db)"
    ),
    None,
)
if ownership_validate_index is None:
    raise SystemExit("Could not find family_ownership.validate(db).")
lines.insert(
    ownership_validate_index + 1,
    f"{indent}family_workspace.validate(db)",
)

migrations_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
parse(migrations_path)


# ---------------------------------------------------------------------------
# Ensure the workspace before any personal request reaches a route.
# ---------------------------------------------------------------------------
main_path = REPO_ROOT / "app/main.py"
main = main_path.read_text(encoding="utf-8")

if "from app.database import get_db, init_db" not in main:
    if "from app.database import init_db\n" in main:
        main = main.replace(
            "from app.database import init_db\n",
            "from app.database import get_db, init_db\n",
            1,
        )
    elif "from app.database import init_db, get_db\n" not in main:
        raise SystemExit("Could not update the app.database import in main.py.")

workspace_import = (
    "from app.db.family_workspace import ensure_personal_workspace\n"
)
if workspace_import not in main:
    database_import = "from app.database import get_db, init_db\n"
    main = main.replace(
        database_import,
        database_import + workspace_import,
        1,
    )

workspace_guard = '''    if user["role"] in {"owner", "member"}:
        with get_db() as db:
            ensure_personal_workspace(db, int(user["id"]))

'''
if "ensure_personal_workspace(db, int(user[\"id\"]))" not in main:
    token_anchor = "    token = bind_request_user(user[\"id\"])\n"
    if token_anchor not in main:
        raise SystemExit(
            "Could not find the M9 request-user binding in main.py."
        )
    main = main.replace(token_anchor, workspace_guard + token_anchor, 1)

main = main.replace(
    'version="0.3.0-client-hunting-mvp"',
    'version="0.4.0-family-workspaces"',
)
main_path.write_text(main, encoding="utf-8")
parse(main_path)


# ---------------------------------------------------------------------------
# Create a blank member workspace in the same transaction as account creation.
# ---------------------------------------------------------------------------
team_path = REPO_ROOT / "app/services/team_users.py"
team = team_path.read_text(encoding="utf-8")
workspace_import = (
    "from app.db.family_workspace import ensure_personal_workspace\n"
)
if workspace_import not in team:
    marker = "from app.services.passwords import hash_password\n"
    if marker not in team:
        raise SystemExit("Could not find team_users import anchor.")
    team = team.replace(marker, workspace_import + marker, 1)

if "ensure_personal_workspace(db, created_user_id)" not in team:
    anchor = "    created = get_user_for_management(db, int(cursor.lastrowid))\n"
    if anchor not in team:
        raise SystemExit(
            "Could not find the managed-user reload anchor in team_users.py."
        )
    replacement = '''    created_user_id = int(cursor.lastrowid)
    if safe_role == "member":
        ensure_personal_workspace(db, created_user_id)

    created = get_user_for_management(db, created_user_id)
'''
    team = team.replace(anchor, replacement, 1)

team_path.write_text(team, encoding="utf-8")
parse(team_path)


# ---------------------------------------------------------------------------
# Make owner seeds compatible with per-user uniqueness.
# ---------------------------------------------------------------------------
goals_seed = '''def seed(db: sqlite3.Connection) -> None:
    db.execute(
        """
        INSERT OR IGNORE INTO profile
        (id, name, wealth_goal, weekday_hours, weekend_rule, strongest_skills, primary_blocker)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            1,
            "Mark",
            "Build a business that reaches at least USD 10,000/month and eventually "
            "supports a team.",
            "2-3 focused hours on weekdays",
            "Protect weekends for family whenever possible",
            "Python, SQL, Power BI, data engineering, automation",
            "Finding qualified clients and turning skills into consistent revenue",
        ),
    )
    seed_goals = [
        ("Reach USD 10,000/month in business income", "wealth", 10),
        ("Build a business with a team", "business", 9),
        ("Create a flagship portfolio product", "career", 8),
        ("Protect family weekends", "family", 10),
    ]
    for title, category, priority in seed_goals:
        db.execute(
            """
            INSERT INTO goals (title, category, priority)
            SELECT ?, ?, ?
            WHERE NOT EXISTS (SELECT 1 FROM goals WHERE title = ?)
            """,
            (title, category, priority, title),
        )

    owner = db.execute(
        """
        SELECT id
        FROM users
        WHERE role = 'owner'
        ORDER BY active DESC, id
        LIMIT 1
        """
    ).fetchone()
    project_columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(projects)").fetchall()
    }
    project_values = (
        "MARK OS v0.1",
        "Build a personal operating system that observes current reality and gives "
        "the highest-leverage next action.",
        10,
        10,
        "Finish the revised Quest Engine, then add budget-safe AI chat.",
    )
    if owner is not None and "user_id" in project_columns:
        owner_id = int(owner["id"])
        db.execute(
            """
            INSERT INTO projects
                (user_id, name, purpose, status, priority, progress, next_action)
            SELECT ?, ?, ?, 'active', ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1
                FROM projects
                WHERE user_id = ? AND name = ?
            )
            """,
            (owner_id, *project_values, owner_id, project_values[0]),
        )
    else:
        db.execute(
            """
            INSERT INTO projects
                (name, purpose, status, priority, progress, next_action)
            SELECT ?, ?, 'active', ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM projects WHERE name = ?
            )
            """,
            (*project_values, project_values[0]),
        )
'''
replace_function(REPO_ROOT / "app/db/goals.py", "seed", goals_seed)

memory_seed = '''def seed(db: sqlite3.Connection) -> None:
    owner = db.execute(
        """
        SELECT id
        FROM users
        WHERE role = 'owner'
        ORDER BY active DESC, id
        LIMIT 1
        """
    ).fetchone()
    columns = {
        row["name"]
        for row in db.execute("PRAGMA table_info(memories)").fetchall()
    }
    memory_value = (
        "A quest can be created, opened, started, blocked, updated, and completed. "
        "Updates preserve progress, notes, minutes, and timestamp history. "
        "Completion requires a result, records evidence and actual time, creates a "
        "timeline event, and awards immutable XP exactly once in a transaction. "
        "Hidden threshold crossing records level-up history."
    )
    memory_key = "phase_4_revised_dod"

    if owner is not None and "user_id" in columns:
        owner_id = int(owner["id"])
        db.execute(
            """
            INSERT INTO memories
                (user_id, memory_type, memory_key, memory_value,
                 importance, source)
            SELECT ?, 'product_principle', ?, ?, 9, 'phase_4_revised'
            WHERE NOT EXISTS (
                SELECT 1
                FROM memories
                WHERE user_id = ? AND memory_key = ?
            )
            """,
            (owner_id, memory_key, memory_value, owner_id, memory_key),
        )
    else:
        db.execute(
            """
            INSERT INTO memories
                (memory_type, memory_key, memory_value, importance, source)
            SELECT 'product_principle', ?, ?, 9, 'phase_4_revised'
            WHERE NOT EXISTS (
                SELECT 1 FROM memories WHERE memory_key = ?
            )
            """,
            (memory_key, memory_value, memory_key),
        )
'''
replace_function(REPO_ROOT / "app/db/memory.py", "seed", memory_seed)


# ---------------------------------------------------------------------------
# Final family-aware navigation.
# ---------------------------------------------------------------------------
base_path = REPO_ROOT / "app/templates/base.html"
base = base_path.read_text(encoding="utf-8")

base = base.replace(
    "request.state.current_user.role == 'owner' else "
    "('/family/setup' if request.state.current_user and "
    "request.state.current_user.role == 'member' else '/crm')",
    "request.state.current_user.role in ['owner', 'member'] else '/crm'",
)
base = base.replace(
    "request.state.current_user.role == 'owner' %}",
    "request.state.current_user.role in ['owner', 'member'] %}",
    1,
)

base_lines = base.splitlines()

# Remove the temporary M7 member-only setup navigation branch. The following
# generic authenticated branch remains the lead-sourcer CRM navigation.
member_start = next(
    (
        index
        for index, line in enumerate(base_lines)
        if "elif request.state.current_user" in line
        and "role == 'member'" in line
    ),
    None,
)
if member_start is not None:
    member_end = next(
        (
            index
            for index in range(member_start + 1, len(base_lines))
            if "{% elif request.state.current_user %}" in base_lines[index]
        ),
        None,
    )
    if member_end is None:
        raise SystemExit("Could not close the M7 member navigation branch.")
    del base_lines[member_start:member_end]


def wrap_owner_only(match_text: str) -> None:
    target_index = next(
        (
            index
            for index, line in enumerate(base_lines)
            if match_text in line
        ),
        None,
    )
    if target_index is None:
        raise SystemExit(f"Could not find navigation item: {match_text}")

    previous = (
        base_lines[target_index - 1].strip()
        if target_index > 0
        else ""
    )
    if previous == "{% if request.state.current_user.role == 'owner' %}":
        return

    indent = base_lines[target_index][
        : len(base_lines[target_index])
        - len(base_lines[target_index].lstrip())
    ]
    base_lines[target_index:target_index + 1] = [
        indent + "{% if request.state.current_user.role == 'owner' %}",
        base_lines[target_index],
        indent + "{% endif %}",
    ]


wrap_owner_only("request.url.path.startswith('/crm')")
wrap_owner_only("request.url.path.startswith('/settings/users')")

base = "\n".join(base_lines) + "\n"
base = base.replace(
    "{% if system_state and request.state.current_user and "
    "request.state.current_user.role == 'owner' %}",
    "{% if system_state and request.state.current_user and "
    "request.state.current_user.role in ['owner', 'member'] %}",
    1,
)
base = base.replace(
    "v0.3.0-client-hunting-mvp",
    "v0.4.0-family-workspaces",
)
base_path.write_text(base, encoding="utf-8")


# ---------------------------------------------------------------------------
# Update README release status.
# ---------------------------------------------------------------------------
readme_path = REPO_ROOT / "README.md"
if readme_path.exists():
    readme = readme_path.read_text(encoding="utf-8")
    marker = "## Family workspaces — M10"
    if marker not in readme:
        readme += """

## Family workspaces — M10

MARK OS now supports three isolated roles:

- **Owner** — full personal OS, Client Hunting CRM, and family account management.
- **Member** — a private dashboard, goals, projects, quests, check-ins, XP,
  history, memories, and chat; no CRM or account-administration access.
- **Lead sourcer** — the narrow Client Hunting CRM surface only.

Each owner/member receives one private profile and game state. New member
workspaces otherwise begin blank. All personal reads and writes are scoped by
`user_id`, cross-user resource IDs return `404`, and database triggers enforce
parent/child ownership. Project names and memory keys are unique per user, so
family members may independently reuse the same labels without collisions.
"""
        readme_path.write_text(readme, encoding="utf-8")


# ---------------------------------------------------------------------------
# Update earlier milestone tests whose intended behavior changes in M10.
# ---------------------------------------------------------------------------
m7_test_path = REPO_ROOT / "tests/test_family_member_foundation.py"
if m7_test_path.exists():
    m7_replacement = '''def test_member_is_confined_to_private_personal_os():
    allowed = (
        ("GET", "/"),
        ("GET", "/goals"),
        ("GET", "/quests"),
        ("GET", "/quests/1"),
        ("GET", "/history"),
        ("GET", "/life-os"),
        ("POST", "/check-in"),
        ("POST", "/quests"),
        ("POST", "/logout"),
    )
    denied = (
        ("GET", "/crm"),
        ("GET", "/settings/users"),
        ("POST", "/crm/leads"),
    )

    assert all(
        can_access_request(MEMBER, method, path)
        for method, path in allowed
    )
    assert not any(
        can_access_request(MEMBER, method, path)
        for method, path in denied
    )
    assert landing_path_for_user(MEMBER) == "/"
    assert permitted_destination(MEMBER, "/") == "/"
    assert permitted_destination(MEMBER, "/crm") == "/"
'''
    m7_source = m7_test_path.read_text(encoding="utf-8")
    if "def test_member_is_confined_to_safe_setup_screen(" in m7_source:
        replace_function(
            m7_test_path,
            "test_member_is_confined_to_safe_setup_screen",
            m7_replacement,
        )
    elif "def test_member_is_confined_to_private_personal_os(" not in m7_source:
        raise SystemExit("Could not locate the M7 member access test.")

m8_test_path = REPO_ROOT / "tests/test_family_data_ownership.py"
if m8_test_path.exists():
    m8_replacement = '''def test_member_starts_with_blank_workspace(
    tmp_path,
    monkeypatch,
):
    database_path = tmp_path / "member-empty.db"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    _configure_owner(monkeypatch)

    database.init_db()

    with database.get_db() as db:
        member = create_member(
            db,
            username="wife",
            display_name="Wife",
            password="family-pass-123",
            password_confirmation="family-pass-123",
        )

    database.init_db()

    db = _connect(database_path)
    member_id = int(member["id"])
    assert db.execute(
        "SELECT COUNT(*) FROM profile WHERE user_id = ?",
        (member_id,),
    ).fetchone()[0] == 1
    assert db.execute(
        "SELECT COUNT(*) FROM game_state WHERE user_id = ?",
        (member_id,),
    ).fetchone()[0] == 1

    for table_name in PERSONAL_TABLES:
        expected = 1 if table_name in {"profile", "game_state"} else 0
        assert db.execute(
            f"""
            SELECT COUNT(*)
            FROM {table_name}
            WHERE user_id = ?
            """,
            (member_id,),
        ).fetchone()[0] == expected
    db.close()
'''
    m8_source = m8_test_path.read_text(encoding="utf-8")
    if "def test_member_starts_with_no_personal_records(" in m8_source:
        replace_function(
            m8_test_path,
            "test_member_starts_with_no_personal_records",
            m8_replacement,
        )
    elif "def test_member_starts_with_blank_workspace(" not in m8_source:
        raise SystemExit("Could not locate the M8 member workspace test.")


# ---------------------------------------------------------------------------
# Final static verification.
# ---------------------------------------------------------------------------
for path in (
    REPO_ROOT / "app/main.py",
    REPO_ROOT / "app/db/migrations.py",
    REPO_ROOT / "app/db/family_workspace.py",
    REPO_ROOT / "app/db/goals.py",
    REPO_ROOT / "app/db/memory.py",
    REPO_ROOT / "app/routes/family.py",
    REPO_ROOT / "app/services/access_control.py",
    REPO_ROOT / "app/services/team_users.py",
    REPO_ROOT / "tests/test_family_workspace_release.py",
):
    parse(path)

print("Installed M10 member workspace initialization.")
print("Enabled member-only personal OS navigation and permissions.")
print("Repaired project and memory uniqueness to be per user.")
print("Updated M7/M8 tests for the completed M10 behavior.")
