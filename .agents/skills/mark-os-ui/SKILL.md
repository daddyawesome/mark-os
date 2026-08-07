---
name: mark-os-ui
description: Use for MARK-OS Jinja/Bulma UI, CRM pages, dashboards, forms, tables, responsive fixes, accessibility, and visual review. Preserve FastAPI + HTMX + Bulma + project CSS.
---

# MARK-OS UI Skill

Use before changing templates, CSS, navigation, forms, dashboards, queues, tables, or responsive layout.

## Stack
Keep FastAPI, Jinja, HTMX, Bulma, and project CSS. Do not introduce React, Vue, Svelte, Tailwind, Bootstrap, Django templates, or a frontend build system unless PROJECT.md explicitly changes the stack.

## Product design goal
MARK-OS is an operating tool, not a landing page. Optimize for clear work state, fast scanning, safe actions, visible ownership, useful density, readable forms/tables, responsive behavior, and accessibility.

## Hard-no patterns
- Do not squeeze headings into character-wide columns beside action groups.
- Do not use oversized marketing heroes on internal CRM pages.
- Avoid decorative labels that do not convey real state.
- Avoid excessive pills, shadows, gradients, random radii, and accent colors.
- Never make destructive actions visually equal to primary actions.
- Do not hide important actions behind hover-only behavior.
- Do not shrink tables until text becomes vertical.
- Do not use placeholder-only form labels.
- Do not use hidden UI as the authorization boundary.

## CRM hierarchy
Prefer:
1. page identity;
2. active workspace;
3. primary action;
4. filters/search;
5. operational data;
6. secondary actions;
7. help only where needed.

Use factual labels: workspace, queue, count, review status, due date, assignee, researcher, Business Development Owner, pipeline.

## Layout
Test the available content width after the sidebar, not only browser width.
Action groups must wrap before titles or data columns become unreadable.
Desktop page titles should normally fit within two lines.

## Forms
Require visible labels, server validation, preserved user input after errors, clear required/optional semantics, keyboard order, and visible focus.
Optimistic-lock conflicts must show a reload/review message and never appear as successful saves.

## Tables and lists
Show useful business metadata. Consider search/filter for larger operational lists.
On narrow screens either preserve essential columns with controlled horizontal scrolling or transform rows into readable stacked records.

## States
Review populated, empty, validation error, permission denied/not found, request-in-flight, success, disabled, and stale-edit conflict states.

## Accessibility
Semantic HTML before ARIA. Keyboard support, visible focus, sufficient contrast, labels, status not relying on color alone, useful table headings, reasonable touch targets, and reduced-motion support when animation exists.

## Responsive review
Check wide desktop, desktop with sidebar, narrow desktop/tablet, and mobile.
Check title wrapping, button wrapping, filters, tables, workspace selector, long names, errors, and empty states.

## Reuse first
Before adding CSS inspect base.html, existing project CSS/tokens, and a comparable current CRM page. Prefer shared project classes over inline styling.

## Permission-aware UI
UI must reflect server permissions, but service-layer authorization remains authoritative. Never expose inaccessible workspaces or record metadata in the DOM for convenience.

## Pre-output checklist
- Existing stack preserved.
- Active workspace visible where relevant.
- Title/action layout works with sidebar.
- Primary/secondary/destructive actions are distinct.
- Empty/error/loading/conflict states are intentional.
- Keyboard/focus behavior remains usable.
- Narrow layouts remain readable.
- Permissions are enforced server-side.
- Relevant tests pass.
- Full suite runs for shared layout/behavior changes.
