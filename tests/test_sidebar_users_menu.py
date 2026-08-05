from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_sidebar_replaces_top_nav_and_has_role_aware_links():
    base = (ROOT / "app/templates/base.html").read_text(
        encoding="utf-8"
    )

    assert "MARK_OS_SIDEBAR_USERS_V1" in base
    assert 'class="mark-sidebar"' in base
    assert "mark-layout-content" in base
    assert "Users" in base
    assert 'href="/settings/users?role=member"' in base
    assert 'href="/settings/users?role=lead_sourcer"' in base
    assert 'href="/settings/users?role=relationship_manager"' in base
    assert 'href="/relationship-manager"' in base
    assert "request.state.current_user.role == 'owner'" in base
    assert "request.state.current_user.role in ['owner', 'member']" in base


def test_users_page_supports_family_and_sourcer_filtering():
    route = (ROOT / "app/routes/users.py").read_text(
        encoding="utf-8"
    )
    template = (ROOT / "app/templates/users.html").read_text(
        encoding="utf-8"
    )

    assert "role: str | None = None" in route
    assert '"selected_role": selected_role' in route
    assert '"relationship_manager"' in route

    assert "Family users." in template
    assert "Lead sourcers." in template
    assert "Relationship managers." in template
    assert "/settings/users?role=member" in template
    assert "/settings/users?role=lead_sourcer" in template
    assert "/settings/users?role=relationship_manager" in template
    assert "Team Access" not in template
