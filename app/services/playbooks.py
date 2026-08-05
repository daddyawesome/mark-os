from __future__ import annotations

import html
import re
import sqlite3
from collections.abc import Iterable
from typing import Any

from markupsafe import Markup


MAX_SLUG_LENGTH = 100
MAX_TITLE_LENGTH = 200
MAX_PLAYBOOK_LENGTH = 250_000


def _required_text(value: str, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text.")
    clean = value.strip()
    if not clean:
        raise ValueError(f"{field_name} is required.")
    if len(clean) > maximum:
        raise ValueError(
            f"{field_name} must be {maximum} characters or fewer."
        )
    return clean


def _clean_slug(value: str) -> str:
    clean = _required_text(value, "Playbook slug", MAX_SLUG_LENGTH)
    normalized = re.sub(r"[^a-z0-9]+", "-", clean.casefold()).strip("-")
    if not normalized:
        raise ValueError("Playbook slug must contain a letter or number.")
    return normalized


def _positive_id(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return value


def _active_user(
    db: sqlite3.Connection,
    user_id: int,
) -> sqlite3.Row:
    safe_user_id = _positive_id(user_id, "User ID")
    row = db.execute(
        """
        SELECT id, username, display_name, role, active
        FROM users
        WHERE id = ? AND active = 1
        """,
        (safe_user_id,),
    ).fetchone()
    if row is None:
        raise ValueError("The assigned user must be active.")
    return row


def upsert_playbook(
    db: sqlite3.Connection,
    *,
    slug: str,
    title: str,
    markdown_content: str,
    created_by_user_id: int | None = None,
    active: bool = True,
) -> dict[str, Any]:
    safe_slug = _clean_slug(slug)
    clean_title = _required_text(title, "Playbook title", MAX_TITLE_LENGTH)
    clean_markdown = _required_text(
        markdown_content,
        "Playbook content",
        MAX_PLAYBOOK_LENGTH,
    )
    creator_id = None
    if created_by_user_id is not None:
        creator_id = int(_active_user(db, created_by_user_id)["id"])

    db.execute(
        """
        INSERT INTO playbooks (
            slug,
            title,
            markdown_content,
            active,
            created_by_user_id,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(slug) DO UPDATE SET
            title = excluded.title,
            markdown_content = excluded.markdown_content,
            active = excluded.active,
            created_by_user_id = COALESCE(
                excluded.created_by_user_id,
                playbooks.created_by_user_id
            ),
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            safe_slug,
            clean_title,
            clean_markdown,
            1 if active else 0,
            creator_id,
        ),
    )
    row = db.execute(
        "SELECT * FROM playbooks WHERE slug = ?",
        (safe_slug,),
    ).fetchone()
    if row is None:
        raise RuntimeError("Playbook could not be reloaded.")
    return dict(row)


def assign_playbook_to_user(
    db: sqlite3.Connection,
    *,
    playbook_id: int,
    user_id: int,
) -> None:
    safe_playbook_id = _positive_id(playbook_id, "Playbook ID")
    user = _active_user(db, user_id)
    if user["role"] != "relationship_manager":
        raise ValueError(
            "Playbooks in this phase can be assigned only to "
            "Relationship Manager accounts."
        )

    playbook = db.execute(
        "SELECT id FROM playbooks WHERE id = ? AND active = 1",
        (safe_playbook_id,),
    ).fetchone()
    if playbook is None:
        raise ValueError("Active playbook not found.")

    db.execute(
        """
        INSERT OR IGNORE INTO user_playbook_assignments (
            user_id,
            playbook_id,
            assigned_at
        )
        VALUES (?, ?, CURRENT_TIMESTAMP)
        """,
        (int(user["id"]), safe_playbook_id),
    )


def replace_user_playbook_assignments(
    db: sqlite3.Connection,
    *,
    user_id: int,
    playbook_ids: Iterable[int],
) -> None:
    user = _active_user(db, user_id)
    if user["role"] != "relationship_manager":
        raise ValueError(
            "Only Relationship Manager accounts can receive this playbook."
        )

    normalized_ids = {
        _positive_id(playbook_id, "Playbook ID")
        for playbook_id in playbook_ids
    }
    db.execute(
        "DELETE FROM user_playbook_assignments WHERE user_id = ?",
        (int(user["id"]),),
    )
    for playbook_id in sorted(normalized_ids):
        assign_playbook_to_user(
            db,
            playbook_id=playbook_id,
            user_id=int(user["id"]),
        )


def get_primary_playbook_for_user(
    db: sqlite3.Connection,
    user_id: int,
) -> dict[str, Any] | None:
    safe_user_id = _positive_id(user_id, "User ID")
    row = db.execute(
        """
        SELECT
            p.*,
            a.assigned_at
        FROM user_playbook_assignments AS a
        JOIN playbooks AS p
          ON p.id = a.playbook_id
        WHERE a.user_id = ?
          AND p.active = 1
        ORDER BY a.assigned_at DESC, p.id DESC
        LIMIT 1
        """,
        (safe_user_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def _inline(text: str) -> str:
    escaped = html.escape(text, quote=True)
    escaped = re.sub(
        r"`([^`]+)`",
        r"<code>\1</code>",
        escaped,
    )
    escaped = re.sub(
        r"\*\*([^*]+)\*\*",
        r"<strong>\1</strong>",
        escaped,
    )
    escaped = re.sub(
        r"(?<!\*)\*([^*]+)\*(?!\*)",
        r"<em>\1</em>",
        escaped,
    )
    return escaped


def render_markdown_safely(markdown_content: str) -> Markup:
    """Render the internal playbook without allowing raw HTML or scripts."""
    text = str(markdown_content or "")
    lines = text.splitlines()
    output: list[str] = []
    paragraph: list[str] = []
    list_type: str | None = None
    blockquote: list[str] = []
    index = 0

    def close_list() -> None:
        nonlocal list_type
        if list_type is not None:
            output.append(f"</{list_type}>")
            list_type = None

    def flush_paragraph() -> None:
        if paragraph:
            output.append(
                "<p>" + " ".join(_inline(part) for part in paragraph) + "</p>"
            )
            paragraph.clear()

    def flush_blockquote() -> None:
        if blockquote:
            output.append(
                "<blockquote><p>"
                + " ".join(_inline(part) for part in blockquote)
                + "</p></blockquote>"
            )
            blockquote.clear()

    while index < len(lines):
        raw = lines[index].rstrip()
        stripped = raw.strip()

        if not stripped:
            flush_paragraph()
            flush_blockquote()
            close_list()
            index += 1
            continue

        if stripped in {"---", "***", "___"}:
            flush_paragraph()
            flush_blockquote()
            close_list()
            output.append("<hr>")
            index += 1
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            flush_paragraph()
            flush_blockquote()
            close_list()
            level = len(heading.group(1))
            output.append(
                f"<h{level}>{_inline(heading.group(2))}</h{level}>"
            )
            index += 1
            continue

        if stripped.startswith(">"):
            flush_paragraph()
            close_list()
            blockquote.append(stripped[1:].strip())
            index += 1
            continue
        flush_blockquote()

        if "|" in stripped and index + 1 < len(lines):
            separator = lines[index + 1].strip()
            if re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", separator):
                flush_paragraph()
                close_list()
                headers = [
                    cell.strip()
                    for cell in stripped.strip("|").split("|")
                ]
                output.append("<div class=\"table-container\"><table class=\"table is-fullwidth is-striped\"><thead><tr>")
                output.extend(
                    f"<th>{_inline(cell)}</th>" for cell in headers
                )
                output.append("</tr></thead><tbody>")
                index += 2
                while index < len(lines) and "|" in lines[index] and lines[index].strip():
                    cells = [
                        cell.strip()
                        for cell in lines[index].strip().strip("|").split("|")
                    ]
                    output.append("<tr>")
                    output.extend(
                        f"<td>{_inline(cell)}</td>" for cell in cells
                    )
                    output.append("</tr>")
                    index += 1
                output.append("</tbody></table></div>")
                continue

        unordered = re.match(r"^[-*+]\s+(.+)$", stripped)
        ordered = re.match(r"^\d+[.)]\s+(.+)$", stripped)
        if unordered or ordered:
            flush_paragraph()
            target_type = "ul" if unordered else "ol"
            if list_type != target_type:
                close_list()
                output.append(f"<{target_type}>")
                list_type = target_type
            item = (unordered or ordered).group(1)
            checkbox = re.match(r"^\[([ xX])\]\s*(.*)$", item)
            if checkbox:
                symbol = "☑" if checkbox.group(1).casefold() == "x" else "☐"
                item_html = f"{symbol} {_inline(checkbox.group(2))}"
            else:
                item_html = _inline(item)
            output.append(f"<li>{item_html}</li>")
            index += 1
            continue

        close_list()
        paragraph.append(stripped)
        index += 1

    flush_paragraph()
    flush_blockquote()
    close_list()
    return Markup("\n".join(output))
