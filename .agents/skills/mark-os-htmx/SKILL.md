---
name: mark-os-htmx
description: Use for MARK-OS hx-* attributes, FastAPI/Jinja fragments, live search/filter, inline edit, asynchronous forms, OOB swaps, request synchronization, and progressive enhancement.
---

# MARK-OS HTMX Skill

Use whenever touching hx-* behavior, partial responses, inline edits, asynchronous forms, search/filter, or OOB updates.

## Mental model
semantic HTML/form -> HTMX request -> FastAPI route -> service authorization/business logic -> Jinja HTML fragment/full page -> explicit target/swap

State and authorization stay on the server.

## Rules
- Return HTML fragments for HTMX UI interactions unless an existing endpoint contract requires JSON.
- Preserve FastAPI + Jinja + HTMX + Bulma.
- Do not duplicate business rules in JavaScript.
- Do not put authorization in hx-* attributes.
- Resolve workspace membership server-side on every CRM request.
- Never trust hidden organization IDs as authorization.
- Preserve normal link/form fallbacks where practical.

## Progressive enhancement
Keep real href/action/method/name attributes. Server validation must work without HTMX. Use HX-Request to choose fragment versus full page when useful.

## Targets and swaps
Target the smallest stable component. Prefer outerHTML for self-contained components and innerHTML for stable shells. Use OOB swaps only for small independent facts like queue counts or status badges.

## Forms and validation
Invalid form -> return form fragment with field errors.
Stale optimistic edit -> return conflict UI and preserve newer DB state.
Success -> return normalized saved component.
Permission failure -> existing safe 403/404 convention.
Unexpected failure -> generic UI + structured server log.

## Request synchronization
Use hx-disabled-elt, hx-indicator, hx-sync, and debounced changed delay for search when appropriate. Client synchronization never replaces request-key idempotency or row-version checks.

## Workspace preservation
Every CRM HTMX request must retain active workspace context through validated server state. Never include inaccessible workspaces or treat an arbitrary organization_id as permission.

## CSRF and mutation safety
Preserve existing cross-site protections. Mutations are not GETs. Preserve idempotency and optimistic edit tokens.

## History
Use history for navigable state such as workspace switch, durable filters, and lead detail. Any pushed URL must be safe to load directly.

## HTMX inheritance
Review inherited hx-confirm, hx-target, and hx-boost. Explicitly unset/disinherit when required.

## Search/filter
Debounce, scope results by active organization, return intentional empty states, and prevent stale/out-of-order results.

## Archive/delete
Server success must happen before removing UI. Preserve history/activity rules, XP correctness, and workspace isolation.

## Testing
Test server behavior, not just hx-* strings: full-page request, HTMX request, fragment, validation, permission failure, active workspace, direct cross-workspace request, optimistic conflict, idempotent retry, and OOB updates where relevant.

## Pre-output checklist
- HTML fragments, not a client JSON app.
- Normal semantics preserved.
- Workspace resolved server-side.
- Service authorization unchanged or stronger.
- No mutation by GET.
- Validation/conflict server-owned.
- Request state visible.
- Racing requests handled.
- Small stable swap target.
- Inheritance reviewed.
- Cross-workspace tests included when relevant.
