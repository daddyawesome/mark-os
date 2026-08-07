from __future__ import annotations

import sqlite3
from typing import Any

from app.db.family_workspace import ensure_personal_workspace
from app.db.organizations import MEMBERSHIP_ROLES, organization_id_by_slug
from app.services.passwords import hash_password, verify_password


MAX_USERNAME_LENGTH = 50
MAX_DISPLAY_NAME_LENGTH = 100
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 200
MANAGED_ROLES = {"member", "lead_sourcer", "relationship_manager"}


def _positive_id(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return value


def _required_text(value: str, field_name: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text.")
    clean = " ".join(value.strip().split())
    if not clean:
        raise ValueError(f"{field_name} is required.")
    if len(clean) > maximum:
        raise ValueError(f"{field_name} must be {maximum} characters or fewer.")
    return clean


def _validated_password(
    password: str,
    password_confirmation: str,
) -> str:
    if not isinstance(password, str):
        raise ValueError("Password must be text.")
    if password != password_confirmation:
        raise ValueError("Password confirmation does not match.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be {MAX_PASSWORD_LENGTH} characters or fewer."
        )
    return password


def _validated_managed_role(role: str) -> str:
    clean_role = (role or "").strip().casefold()
    if clean_role not in MANAGED_ROLES:
        raise ValueError("Unsupported account type.")
    return clean_role


def _validated_membership_role(global_role: str, membership_role: str) -> str:
    clean = str(membership_role or "").strip().casefold()
    if clean not in MEMBERSHIP_ROLES:
        raise ValueError("Unsupported workspace role.")
    if global_role == "lead_sourcer" and clean != "crm_contributor":
        raise ValueError("Lead Researchers must use CRM Contributor workspace access.")
    if global_role == "relationship_manager" and clean not in {
        "crm_contributor",
        "workspace_owner",
    }:
        raise ValueError(
            "Relationship Managers may use CRM Contributor or Workspace Owner access."
        )
    if global_role not in {"lead_sourcer", "relationship_manager"}:
        raise ValueError("This account type does not use CRM workspace access.")
    return clean


def _require_global_owner(db: sqlite3.Connection, user_id: int) -> None:
    row = db.execute(
        "SELECT role, active FROM users WHERE id = ?",
        (_positive_id(user_id, "Acting user ID"),),
    ).fetchone()
    if row is None or row["role"] != "owner" or not bool(row["active"]):
        raise ValueError("An active global Owner is required.")


def list_user_workspace_memberships(
    db: sqlite3.Connection,
    user_id: int,
) -> list[dict[str, Any]]:
    safe_user_id = _positive_id(user_id, "User ID")
    rows = db.execute(
        """
        SELECT
            o.id AS organization_id,
            o.slug,
            o.name,
            m.membership_role,
            COALESCE(m.active, 0) AS active,
            CASE WHEN m.user_id IS NULL THEN 0 ELSE 1 END AS configured
        FROM organizations AS o
        LEFT JOIN organization_memberships AS m
          ON m.organization_id = o.id
         AND m.user_id = ?
        ORDER BY
            CASE WHEN o.slug = 'mark-agency' THEN 0 ELSE 1 END,
            o.name COLLATE NOCASE,
            o.id
        """,
        (safe_user_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def set_workspace_membership(
    db: sqlite3.Connection,
    *,
    target_user_id: int,
    acting_user_id: int,
    workspace_slug: str,
    membership_role: str,
    active: bool,
) -> dict[str, Any]:
    """Grant/change/revoke one CRM workspace membership and revoke sessions."""
    target_id = _positive_id(target_user_id, "Target user ID")
    _require_global_owner(db, acting_user_id)
    target = db.execute(
        "SELECT id, role, active FROM users WHERE id = ?",
        (target_id,),
    ).fetchone()
    if target is None:
        raise ValueError("User not found.")
    if target["role"] == "owner":
        raise ValueError("Global Owner workspace memberships are managed automatically.")
    if target["role"] not in {"lead_sourcer", "relationship_manager"}:
        raise ValueError("Only CRM staff can receive business workspace access.")

    safe_role = _validated_membership_role(target["role"], membership_role)
    organization_id = organization_id_by_slug(db, workspace_slug)
    existing = db.execute(
        """
        SELECT membership_role, active
        FROM organization_memberships
        WHERE user_id = ? AND organization_id = ?
        """,
        (target_id, organization_id),
    ).fetchone()
    desired_active = 1 if active else 0
    if (
        existing is not None
        and existing["membership_role"] == safe_role
        and int(existing["active"]) == desired_active
    ):
        return next(
            row
            for row in list_user_workspace_memberships(db, target_id)
            if int(row["organization_id"]) == organization_id
        )

    db.execute(
        """
        INSERT INTO organization_memberships (
            user_id, organization_id, membership_role, active
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, organization_id) DO UPDATE SET
            membership_role = excluded.membership_role,
            active = excluded.active
        """,
        (target_id, organization_id, safe_role, desired_active),
    )

    # Permission changes take effect immediately for all existing sessions.
    db.execute(
        """
        UPDATE users
        SET session_version = session_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (target_id,),
    )

    if not active:
        owner_id = get_primary_owner_id(db, active_only=True)
        if owner_id is None:
            raise ValueError("An active Owner is required before revoking workspace access.")
        db.execute(
            """
            UPDATE leads
            SET assigned_to_user_id = ?,
                row_version = row_version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE organization_id = ?
              AND assigned_to_user_id = ?
              AND deleted_at IS NULL
            """,
            (owner_id, organization_id, target_id),
        )
        db.execute(
            """
            UPDATE leads
            SET business_development_owner_user_id = NULL,
                row_version = row_version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE organization_id = ?
              AND business_development_owner_user_id = ?
              AND deleted_at IS NULL
            """,
            (organization_id, target_id),
        )

    return next(
        row
        for row in list_user_workspace_memberships(db, target_id)
        if int(row["organization_id"]) == organization_id
    )


def get_primary_owner_id(
    db: sqlite3.Connection,
    *,
    active_only: bool = False,
) -> int | None:
    condition = "AND active = 1" if active_only else ""
    row = db.execute(
        f"""
        SELECT id
        FROM users
        WHERE role = 'owner'
        {condition}
        ORDER BY active DESC, id
        LIMIT 1
        """
    ).fetchone()
    return int(row["id"]) if row is not None else None


def list_users_with_stats(
    db: sqlite3.Connection,
) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT
            u.id,
            u.username,
            u.display_name,
            u.role,
            u.active,
            u.must_change_password,
            u.session_version,
            u.last_login_at,
            u.created_at,
            u.updated_at,
            COUNT(l.id) AS lead_count,
            COALESCE(
                SUM(
                    CASE WHEN l.id IS NOT NULL
                               AND l.deleted_at IS NULL
                         THEN 1 ELSE 0 END
                ),
                0
            ) AS active_lead_count,
            (
                SELECT COUNT(*)
                FROM leads AS relationship_lead
                WHERE relationship_lead.business_development_owner_user_id = u.id
            ) AS business_development_lead_count,
            (
                SELECT COUNT(*)
                FROM leads AS relationship_lead
                WHERE relationship_lead.business_development_owner_user_id = u.id
                  AND relationship_lead.deleted_at IS NULL
            ) AS active_business_development_lead_count
        FROM users AS u
        LEFT JOIN leads AS l
          ON l.created_by_user_id = u.id
        GROUP BY
            u.id,
            u.username,
            u.display_name,
            u.role,
            u.active,
            u.must_change_password,
            u.session_version,
            u.last_login_at,
            u.created_at,
            u.updated_at
        ORDER BY
            CASE
                WHEN u.role = 'owner' THEN 0
                WHEN u.role = 'member' THEN 1
                WHEN u.role = 'lead_sourcer' THEN 2
                WHEN u.role = 'relationship_manager' THEN 3
                ELSE 4
            END,
            u.active DESC,
            u.display_name COLLATE NOCASE,
            u.id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_user_for_management(
    db: sqlite3.Connection,
    user_id: int,
) -> dict[str, Any] | None:
    safe_user_id = _positive_id(user_id, "User ID")
    row = db.execute(
        """
        SELECT
            u.id,
            u.username,
            u.display_name,
            u.role,
            u.active,
            u.must_change_password,
            u.session_version,
            u.last_login_at,
            u.created_at,
            u.updated_at,
            COUNT(l.id) AS lead_count,
            COALESCE(
                SUM(
                    CASE WHEN l.id IS NOT NULL
                               AND l.deleted_at IS NULL
                         THEN 1 ELSE 0 END
                ),
                0
            ) AS active_lead_count,
            (
                SELECT COUNT(*)
                FROM leads AS relationship_lead
                WHERE relationship_lead.business_development_owner_user_id = u.id
            ) AS business_development_lead_count,
            (
                SELECT COUNT(*)
                FROM leads AS relationship_lead
                WHERE relationship_lead.business_development_owner_user_id = u.id
                  AND relationship_lead.deleted_at IS NULL
            ) AS active_business_development_lead_count
        FROM users AS u
        LEFT JOIN leads AS l
          ON l.created_by_user_id = u.id
        WHERE u.id = ?
        GROUP BY
            u.id,
            u.username,
            u.display_name,
            u.role,
            u.active,
            u.must_change_password,
            u.session_version,
            u.last_login_at,
            u.created_at,
            u.updated_at
        """,
        (safe_user_id,),
    ).fetchone()
    if row is None:
        return None
    managed = dict(row)
    managed["workspace_memberships"] = list_user_workspace_memberships(
        db, safe_user_id
    )
    return managed


def create_managed_user(
    db: sqlite3.Connection,
    *,
    username: str,
    display_name: str,
    password: str,
    password_confirmation: str,
    role: str,
    workspace_slug: str | None = None,
    membership_role: str = "crm_contributor",
) -> dict[str, Any]:
    clean_username = _required_text(
        username,
        "Username",
        MAX_USERNAME_LENGTH,
    )
    clean_display_name = _required_text(
        display_name,
        "Display name",
        MAX_DISPLAY_NAME_LENGTH,
    )
    safe_password = _validated_password(password, password_confirmation)
    safe_role = _validated_managed_role(role)
    safe_membership_role = (
        _validated_membership_role(safe_role, membership_role)
        if safe_role in {"lead_sourcer", "relationship_manager"}
        else None
    )

    try:
        cursor = db.execute(
            """
            INSERT INTO users (
                username,
                display_name,
                password_hash,
                role,
                active,
                must_change_password,
                session_version
            )
            VALUES (?, ?, ?, ?, 1, 1, 1)
            """,
            (
                clean_username,
                clean_display_name,
                hash_password(safe_password),
                safe_role,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError("That username is already in use.") from exc

    created_user_id = int(cursor.lastrowid)
    if safe_role == "member":
        ensure_personal_workspace(db, created_user_id)
    elif safe_role in {"lead_sourcer", "relationship_manager"}:
        organization_id = organization_id_by_slug(
            db,
            workspace_slug or "mark-agency",
        )
        db.execute(
            """
            INSERT INTO organization_memberships (
                user_id,
                organization_id,
                membership_role,
                active
            )
            VALUES (?, ?, ?, 1)
            """,
            (created_user_id, organization_id, safe_membership_role),
        )

    created = get_user_for_management(db, created_user_id)
    if created is None:
        raise RuntimeError("Created user could not be reloaded.")
    return created


def create_lead_sourcer(
    db: sqlite3.Connection,
    *,
    username: str,
    display_name: str,
    password: str,
    password_confirmation: str,
    workspace_slug: str = "mark-agency",
) -> dict[str, Any]:
    return create_managed_user(
        db,
        username=username,
        display_name=display_name,
        password=password,
        password_confirmation=password_confirmation,
        role="lead_sourcer",
        workspace_slug=workspace_slug,
    )


def create_relationship_manager(
    db: sqlite3.Connection,
    *,
    username: str,
    display_name: str,
    password: str,
    password_confirmation: str,
    workspace_slug: str = "mark-agency",
    membership_role: str = "crm_contributor",
) -> dict[str, Any]:
    return create_managed_user(
        db,
        username=username,
        display_name=display_name,
        password=password,
        password_confirmation=password_confirmation,
        role="relationship_manager",
        workspace_slug=workspace_slug,
        membership_role=membership_role,
    )


def create_member(
    db: sqlite3.Connection,
    *,
    username: str,
    display_name: str,
    password: str,
    password_confirmation: str,
) -> dict[str, Any]:
    return create_managed_user(
        db,
        username=username,
        display_name=display_name,
        password=password,
        password_confirmation=password_confirmation,
        role="member",
    )


def set_user_active(
    db: sqlite3.Connection,
    *,
    target_user_id: int,
    acting_user_id: int,
    active: bool,
) -> dict[str, Any]:
    target_id = _positive_id(target_user_id, "Target user ID")
    actor_id = _positive_id(acting_user_id, "Acting user ID")

    target = db.execute(
        """
        SELECT id, username, display_name, role, active
        FROM users
        WHERE id = ?
        """,
        (target_id,),
    ).fetchone()
    if target is None:
        raise ValueError("User not found.")

    if not active and target["role"] == "owner":
        raise ValueError(
            "Owner accounts cannot be deactivated from user management."
        )
    if not active and target_id == actor_id:
        raise ValueError("You cannot deactivate your own account.")

    if bool(target["active"]) == active:
        managed = get_user_for_management(db, target_id)
        if managed is None:
            raise RuntimeError("User could not be reloaded.")
        return managed

    if active:
        db.execute(
            """
            UPDATE users
            SET active = 1,
                session_version = session_version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (target_id,),
        )
        if target["role"] in {"lead_sourcer", "relationship_manager"}:
            has_membership = db.execute(
                """
                SELECT 1
                FROM organization_memberships
                WHERE user_id = ?
                LIMIT 1
                """,
                (target_id,),
            ).fetchone()
            if has_membership is None:
                db.execute(
                    """
                    INSERT INTO organization_memberships (
                        user_id,
                        organization_id,
                        membership_role,
                        active
                    )
                    VALUES (?, ?, 'crm_contributor', 1)
                    """,
                    (
                        target_id,
                        organization_id_by_slug(db, "mark-agency"),
                    ),
                )
    else:
        owner_id = get_primary_owner_id(db, active_only=True)
        if owner_id is None:
            raise ValueError(
                "An active owner is required before disabling this account."
            )

        db.execute(
            """
            UPDATE users
            SET active = 0,
                session_version = session_version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (target_id,),
        )
        db.execute(
            """
            UPDATE leads
            SET assigned_to_user_id = ?,
                row_version = row_version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE assigned_to_user_id = ?
            """,
            (owner_id, target_id),
        )
        db.execute(
            """
            UPDATE leads
            SET business_development_owner_user_id = NULL,
                row_version = row_version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE business_development_owner_user_id = ?
            """,
            (target_id,),
        )

    managed = get_user_for_management(db, target_id)
    if managed is None:
        raise RuntimeError("Updated user could not be reloaded.")
    return managed


def reset_user_password(
    db: sqlite3.Connection,
    *,
    target_user_id: int,
    password: str,
    password_confirmation: str,
) -> dict[str, Any]:
    target_id = _positive_id(target_user_id, "Target user ID")
    safe_password = _validated_password(password, password_confirmation)

    target = db.execute(
        "SELECT id FROM users WHERE id = ?",
        (target_id,),
    ).fetchone()
    if target is None:
        raise ValueError("User not found.")

    db.execute(
        """
        UPDATE users
        SET password_hash = ?,
            must_change_password = 1,
            session_version = session_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (hash_password(safe_password), target_id),
    )

    managed = get_user_for_management(db, target_id)
    if managed is None:
        raise RuntimeError("Updated user could not be reloaded.")
    return managed

def change_own_password(
    db: sqlite3.Connection,
    *,
    user_id: int,
    current_password: str,
    password: str,
    password_confirmation: str,
) -> dict[str, Any]:
    """Replace the authenticated user's password and revoke other sessions."""
    safe_user_id = _positive_id(user_id, "User ID")
    safe_password = _validated_password(password, password_confirmation)
    row = db.execute(
        """
        SELECT id, password_hash
        FROM users
        WHERE id = ? AND active = 1
        """,
        (safe_user_id,),
    ).fetchone()
    if row is None:
        raise ValueError("User not found.")
    if not verify_password(current_password, row["password_hash"]):
        raise ValueError("Current password is incorrect.")
    if verify_password(safe_password, row["password_hash"]):
        raise ValueError("Choose a new password that differs from the current password.")

    db.execute(
        """
        UPDATE users
        SET password_hash = ?,
            must_change_password = 0,
            session_version = session_version + 1,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (hash_password(safe_password), safe_user_id),
    )
    updated = db.execute(
        """
        SELECT id, username, display_name, role, active,
               must_change_password, session_version,
               last_login_at, created_at, updated_at
        FROM users
        WHERE id = ?
        """,
        (safe_user_id,),
    ).fetchone()
    if updated is None:
        raise RuntimeError("Updated user could not be reloaded.")
    return dict(updated)
