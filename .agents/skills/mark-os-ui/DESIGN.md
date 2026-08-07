# MARK-OS Design Intent

MARK-OS should feel like a focused small-business operating system: trustworthy, practical, calm, information-rich without clutter, and easy for new staff to learn.

It should not look like a generic AI dashboard, startup landing page, crypto dashboard, or unrelated collection of cards.

## Priorities
Users should quickly answer:
- Where am I?
- Which business workspace is active?
- What needs attention?
- What can I do?
- What changed?
- Who owns the next step?

## Workspace identity
Workspace identity must be visible enough to prevent accidental cross-business work without dominating the page. Mark may get a compact selector; single-workspace staff should get a locked label.

## Density
Use more density for lead lists, queues, timelines, reviews, and metrics. Use more breathing room for destructive confirmation, onboarding, imports, conflicts, and critical errors.

## Visual restraint
Prefer neutral surfaces, one primary action treatment, semantic status colors, consistent borders/radii, and modest shadows.

## Consistent verbs
Use the same workflow language: Create, Preview, Submit for review, Approve, Request changes, Reject, Contacted, Follow up, Archive, Restore.

## Source inspiration
This project-specific guidance synthesizes ideas from CleanUI and the Awesome Design Skills registry: avoid generic AI-looking layouts, match layout to content, use restrained visual treatment, define component states, and enforce accessibility. MARK-OS existing components, Bulma, project CSS, workflow rules, and tests remain authoritative.

## Forest Fieldbook visual system

MARK-OS uses an **Orbit-inspired Forest Fieldbook** treatment for the shared
application shell and CRM surfaces.

The goal is not to turn operational data into a cartoon. The goal is to make
the workspace feel human, owned, and memorable while preserving fast scanning
and strong permission cues.

### Visual vocabulary

Use:

- warm paper content surfaces;
- deep pine navigation;
- forest/moss/fern accents;
- slightly irregular borders;
- solid offset shadows rather than glossy glow;
- small sticky-note treatments for summary metrics;
- subtle paper/dot texture;
- tactile "press flat" buttons;
- handwritten/field-note typography only for brand, kickers, and small accents.

Keep system/sans typography for:

- tables;
- form inputs;
- CRM record text;
- dates;
- permissions;
- metrics requiring precise scanning.

### Controlled irregularity

Irregularity is decorative, never structural.

Allowed:

- small border-radius asymmetry;
- tiny metric-card rotations;
- tape-like pseudo-elements on hero/login surfaces;
- hard offset shadows.

Do not rotate:

- tables;
- forms;
- destructive confirmations;
- permission/error text;
- long record cards;
- workspace selectors.

### Forest Fieldbook palette

```text
warm paper      #f3f0df
bright paper    #fffdf3
deep pine       #173c2a
pine black      #082016
moss            #668052
fern paper      #cfddbc
amber note      #efe0aa
berry warning   #a5524c
ink             #203428
```

### Orbit inspiration boundary

The visual direction is inspired by Orbit's human-centered notebook aesthetic:
paper texture, irregular edges, tactile shadows, small rotations, and
human-readable dashboard notes.

MARK-OS does not adopt Orbit's Astro/Preact runtime, Markdown database, or
drag-and-drop behavior. MARK-OS remains FastAPI + Jinja + HTMX + Bulma +
SQLite.

The MARK-OS permission model, service-layer workspace isolation, responsive
CRM rules, and accessibility requirements take precedence over visual
similarity.
