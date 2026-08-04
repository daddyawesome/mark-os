from __future__ import annotations

import subprocess
from pathlib import Path


REQUIRED_FILES = (
    "app/main.py",
    "app/database.py",
    "app/db/family_ownership.py",
    "app/db/family_integrity.py",
    "app/db/migrations.py",
    "app/routes/family.py",
    "app/services/access_control.py",
    "app/services/personal_scope.py",
    "app/services/team_users.py",
    "app/templates/base.html",
    "tests/test_family_isolation.py",
    "tests/test_family_data_ownership.py",
    "tests/test_family_member_foundation.py",
)


missing = [name for name in REQUIRED_FILES if not Path(name).exists()]
if missing:
    raise SystemExit(
        "M10 prerequisites are missing:\n- " + "\n- ".join(missing)
    )

checks = {
    "M7 member role": (
        Path("app/db/users.py"),
        "member",
    ),
    "M8 ownership migration": (
        Path("app/db/family_ownership.py"),
        "user_id",
    ),
    "M9 request scope": (
        Path("app/services/personal_scope.py"),
        "bind_request_user",
    ),
    "M9 integrity triggers": (
        Path("app/db/family_integrity.py"),
        "create_triggers",
    ),
}
for label, (path, marker) in checks.items():
    if marker not in path.read_text(encoding="utf-8"):
        raise SystemExit(f"Missing {label}: {path} lacks {marker!r}.")

branch = subprocess.run(
    ["git", "branch", "--show-current"],
    check=False,
    capture_output=True,
    text=True,
).stdout.strip()

print(f"Branch: {branch or '(not detected)'}")
print("M7 member role detected.")
print("M8 ownership schema detected.")
print("M9 request isolation and integrity triggers detected.")
print("M10 prerequisites passed.")
