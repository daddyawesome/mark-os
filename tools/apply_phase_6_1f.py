from __future__ import annotations

import ast
import shutil
from datetime import datetime
from pathlib import Path


ROOT = Path.cwd()


def _replace_once(
    text: str,
    old: str,
    new: str,
    *,
    label: str,
) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"{label}: expected one match, found {count}."
        )
    return text.replace(old, new, 1)


def _backup(
    path: Path,
    backup_root: Path,
) -> None:
    if not path.exists():
        raise SystemExit(
            f"Required file is missing: {path}"
        )
    destination = backup_root / path.relative_to(ROOT)
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    shutil.copy2(path, destination)


def _validate_python(path: Path) -> None:
    ast.parse(
        path.read_text(encoding="utf-8"),
        filename=str(path),
    )


def _patch_client_hunting(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "change_pipeline_stage" in text:
        print(
            "app/routes/client_hunting.py "
            "is already patched."
        )
        return

    text = _replace_once(
        text,
        (
            "from app.services."
            "lead_research_permissions "
            "import can_edit_research\n"
        ),
        (
            "from app.services."
            "lead_research_permissions import (\n"
            "    LeadPermissionError,\n"
            "    can_approve_outreach,\n"
            "    can_edit_research,\n"
            ")\n"
            "from app.services."
            "lead_pipeline_workflow import (\n"
            "    LeadPipelineRuleError,\n"
            "    change_pipeline_stage,\n"
            "    update_owner_lead,\n"
            ")\n"
        ),
        label="client route workflow imports",
    )

    text = text.replace(
        "    update_lead as update_lead_record,\n",
        "",
        1,
    )
    text = text.replace(
        "    update_lead_pipeline as update_pipeline_record,\n",
        "",
        1,
    )

    text = _replace_once(
        text,
        (
            '    "research_rejected": '
            "'Lead research rejected.',\n"
            "}\n"
        ),
        (
            '    "research_rejected": '
            "'Lead research rejected.',\n"
            '    "outreach_approved": '
            '"Outreach approved. This lead may now '
            'move to Contacted.",\n'
            "}\n"
        ),
        label="outreach notice",
    )

    text = _replace_once(
        text,
        (
            '    "invalid_review": '
            "'The research review decision could "
            "not be saved.',\n"
            "}\n"
        ),
        (
            '    "invalid_review": '
            "'The research review decision could "
            "not be saved.',\n"
            '    "pipeline_rule": '
            '"That pipeline move is not allowed. '
            "Contacted requires approved research "
            "and outreach approval; Proposal "
            "requires Meeting; Won requires "
            'Proposal.",\n'
            "}\n"
        ),
        label="pipeline rule error",
    )

    text = _replace_once(
        text,
        (
            '            "can_edit_research": '
            "can_edit_research(\n"
            "                request.state.current_user,\n"
            "                lead,\n"
            "            ),\n"
        ),
        (
            '            "can_edit_research": '
            "can_edit_research(\n"
            "                request.state.current_user,\n"
            "                lead,\n"
            "            ),\n"
            '            "can_approve_outreach": '
            "can_approve_outreach(\n"
            "                request.state.current_user,\n"
            "                lead,\n"
            "            ),\n"
        ),
        label="lead detail approval context",
    )

    text = _replace_once(
        text,
        (
            "def edit_lead(\n"
            "    lead_id: int,\n"
        ),
        (
            "def edit_lead(\n"
            "    request: Request,\n"
            "    lead_id: int,\n"
        ),
        label="edit route request actor",
    )

    text = _replace_once(
        text,
        (
            "            update_lead_record(\n"
            "                db,\n"
            "                lead_id,\n"
        ),
        (
            "            update_owner_lead(\n"
            "                db,\n"
            "                lead_id,\n"
            "                actor="
            "request.state.current_user,\n"
        ),
        label="guarded full edit",
    )

    text = _replace_once(
        text,
        (
            "        except ValueError:\n"
            "            return RedirectResponse(\n"
            "                url=f\"/crm/leads/{lead_id}"
            "/edit?error=invalid\",\n"
            "                status_code=303,\n"
            "            )\n"
        ),
        (
            "        except LeadPermissionError:\n"
            "            return RedirectResponse(\n"
            "                url=f\"/crm/leads/{lead_id}"
            "/edit?error=forbidden\",\n"
            "                status_code=303,\n"
            "            )\n"
            "        except ValueError:\n"
            "            return RedirectResponse(\n"
            "                url=f\"/crm/leads/{lead_id}"
            "/edit?error=invalid\",\n"
            "                status_code=303,\n"
            "            )\n"
        ),
        label="full edit permission handling",
    )

    text = _replace_once(
        text,
        (
            "def update_pipeline(\n"
            "    lead_id: int,\n"
        ),
        (
            "def update_pipeline(\n"
            "    request: Request,\n"
            "    lead_id: int,\n"
        ),
        label="pipeline route request actor",
    )

    text = _replace_once(
        text,
        (
            "            update_pipeline_record(\n"
            "                db,\n"
            "                lead_id,\n"
            "                pipeline_status="
            "pipeline_status,\n"
            "            )\n"
            "        except ValueError:\n"
            "            return RedirectResponse(\n"
            "                url=f\"/crm/leads/{lead_id}"
            "?error=invalid\",\n"
            "                status_code=303,\n"
            "            )\n"
        ),
        (
            "            change_pipeline_stage(\n"
            "                db,\n"
            "                lead_id,\n"
            "                actor="
            "request.state.current_user,\n"
            "                pipeline_status="
            "pipeline_status,\n"
            "            )\n"
            "        except LeadPermissionError:\n"
            "            return RedirectResponse(\n"
            "                url=f\"/crm/leads/{lead_id}"
            "?error=forbidden\",\n"
            "                status_code=303,\n"
            "            )\n"
            "        except LeadPipelineRuleError:\n"
            "            return RedirectResponse(\n"
            "                url=f\"/crm/leads/{lead_id}"
            "?error=pipeline_rule\",\n"
            "                status_code=303,\n"
            "            )\n"
            "        except ValueError:\n"
            "            return RedirectResponse(\n"
            "                url=f\"/crm/leads/{lead_id}"
            "?error=invalid\",\n"
            "                status_code=303,\n"
            "            )\n"
        ),
        label="guarded quick pipeline",
    )

    path.write_text(text, encoding="utf-8")
    _validate_python(path)
    print("Patched app/routes/client_hunting.py.")


def _patch_lead_research_routes(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "def approve_lead_outreach(" in text:
        print(
            "app/routes/lead_research.py "
            "is already patched."
        )
        return

    route = '''

@router.post(
    "/leads/{lead_id}/outreach/approve"
)
def approve_lead_outreach(
    request: Request,
    lead_id: int,
):
    from app.services.lead_pipeline_workflow import (
        approve_outreach,
    )
    from app.services.lead_research_permissions import (
        can_approve_outreach,
    )

    with get_db() as db:
        lead = get_lead(db, lead_id)
        if (
            lead is None
            or not can_approve_outreach(
                request.state.current_user,
                lead,
            )
        ):
            raise HTTPException(
                status_code=404,
                detail="Lead not found",
            )

        try:
            approve_outreach(
                db,
                lead_id,
                actor=request.state.current_user,
            )
        except LeadPermissionError:
            raise HTTPException(
                status_code=404,
                detail="Lead not found",
            )

    return RedirectResponse(
        url=(
            f"/crm/leads/{lead_id}"
            "?notice=outreach_approved"
        ),
        status_code=303,
    )
'''
    text = text.rstrip() + route + "\n"
    path.write_text(text, encoding="utf-8")
    _validate_python(path)
    print("Patched app/routes/lead_research.py.")


def _patch_lead_detail(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    include = (
        '{% include "partials/'
        'lead_outreach_approval_panel.html" %}'
    )
    if include in text:
        print(
            "app/templates/lead_detail.html "
            "is already patched."
        )
        return

    text = _replace_once(
        text,
        (
            '{% include "partials/'
            'lead_research_review_panel.html" %}\n'
        ),
        (
            '{% include "partials/'
            'lead_research_review_panel.html" %}\n'
            + include
            + "\n"
        ),
        label="outreach panel include",
    )
    path.write_text(text, encoding="utf-8")
    print("Patched app/templates/lead_detail.html.")


def _patch_application_test(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    route_line = (
        '    ("POST", "/crm/leads/{lead_id}/'
        'outreach/approve", '
        '"approve_lead_outreach"),\n'
    )
    if route_line in text:
        print(
            "tests/test_application.py "
            "is already patched."
        )
        return

    text = _replace_once(
        text,
        (
            '    ("POST", "/crm/leads/{lead_id}/'
            'research/review", '
            '"review_lead_research"),\n'
        ),
        (
            '    ("POST", "/crm/leads/{lead_id}/'
            'research/review", '
            '"review_lead_research"),\n'
            + route_line
        ),
        label="expected outreach route",
    )
    path.write_text(text, encoding="utf-8")
    _validate_python(path)
    print("Patched tests/test_application.py.")


def _patch_role_test(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    denied_line = (
        '        ("POST", "/crm/leads/1/'
        'outreach/approve"),\n'
    )
    if denied_line in text:
        print(
            "tests/test_role_permissions.py "
            "is already patched."
        )
        return

    text = _replace_once(
        text,
        (
            '        ("POST", "/crm/leads/1/'
            'pipeline"),\n'
            '        ("POST", "/crm/leads/1/'
            'delete"),\n'
        ),
        (
            '        ("POST", "/crm/leads/1/'
            'pipeline"),\n'
            '        ("POST", "/crm/leads/1/'
            'outreach/approve"),\n'
            '        ("POST", "/crm/leads/1/'
            'delete"),\n'
        ),
        label="owner outreach route permission",
    )

    text = _replace_once(
        text,
        (
            '        ("POST", "/crm/leads/1/'
            'pipeline"),\n'
            '        ("POST", "/crm/leads/1/'
            'next-action"),\n'
        ),
        (
            '        ("POST", "/crm/leads/1/'
            'pipeline"),\n'
            '        ("POST", "/crm/leads/1/'
            'outreach/approve"),\n'
            '        ("POST", "/crm/leads/1/'
            'next-action"),\n'
        ),
        label="sourcer forged outreach denial",
    )

    path.write_text(text, encoding="utf-8")
    _validate_python(path)
    print("Patched tests/test_role_permissions.py.")


def main() -> None:
    required = (
        ROOT / "app/services/lead_pipeline_workflow.py",
        ROOT / (
            "app/templates/partials/"
            "lead_outreach_approval_panel.html"
        ),
        ROOT / "tests/test_lead_pipeline_approval.py",
        ROOT / "app/routes/client_hunting.py",
        ROOT / "app/routes/lead_research.py",
        ROOT / "app/templates/lead_detail.html",
        ROOT / "tests/test_application.py",
        ROOT / "tests/test_role_permissions.py",
    )
    for path in required:
        if not path.exists():
            raise SystemExit(
                f"Required file is missing: {path}"
            )

    modified = (
        ROOT / "app/routes/client_hunting.py",
        ROOT / "app/routes/lead_research.py",
        ROOT / "app/templates/lead_detail.html",
        ROOT / "tests/test_application.py",
        ROOT / "tests/test_role_permissions.py",
    )

    stamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )
    backup_root = (
        ROOT
        / ".mark_os_backups"
        / f"phase_6_1f_{stamp}"
    )
    for path in modified:
        _backup(path, backup_root)

    _patch_client_hunting(modified[0])
    _patch_lead_research_routes(modified[1])
    _patch_lead_detail(modified[2])
    _patch_application_test(modified[3])
    _patch_role_test(modified[4])

    for path in (
        ROOT / "app/services/lead_pipeline_workflow.py",
        ROOT / "tests/test_lead_pipeline_approval.py",
        ROOT / "tools/apply_phase_6_1f.py",
    ):
        _validate_python(path)

    print(f"Backups created under: {backup_root}")
    print("Phase 6.1F installation complete.")


if __name__ == "__main__":
    main()
