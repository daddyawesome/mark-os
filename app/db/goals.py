from __future__ import annotations

import sqlite3

from app.db.schema import ensure_column


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT NOT NULL,
    wealth_goal TEXT NOT NULL,
    weekday_hours TEXT NOT NULL,
    weekend_rule TEXT NOT NULL,
    strongest_skills TEXT NOT NULL,
    primary_blocker TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    priority INTEGER NOT NULL DEFAULT 5,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    purpose TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    priority INTEGER NOT NULL DEFAULT 5,
    progress INTEGER NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
    next_action TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def migrate(db: sqlite3.Connection) -> None:
    ensure_column(db, "projects", "goal_id", "INTEGER REFERENCES goals(id)")


def seed(db: sqlite3.Connection) -> None:
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
