# AGENTS.md

<!-- MARK-OS-SKILLS:START -->
## MARK-OS project skills

Before changing Jinja templates, Bulma/project CSS, forms, tables, dashboards, CRM layout, responsive behavior, or accessibility, read `.agents/skills/mark-os-ui/SKILL.md`.

Before changing any `hx-*` attributes, partial templates, asynchronous forms, live search/filter, inline edit, OOB update, or boosted navigation, also read `.agents/skills/mark-os-htmx/SKILL.md`.

For the product design rationale, read `.agents/skills/mark-os-ui/DESIGN.md`.

These project skills are repository constraints. The frontend stack remains FastAPI + Jinja + HTMX + Bulma + project CSS. Do not introduce a second frontend architecture unless canonical `PROJECT.md` explicitly changes it.

CRM UI/HTMX work must preserve service-layer authorization, organization isolation, optimistic edit protection, request idempotency, and existing security middleware. Hiding a control is never the authorization boundary.

Run focused tests and the full suite when shared layout, permissions, routing, or behavior are affected.
<!-- MARK-OS-SKILLS:END -->
