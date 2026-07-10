# Phase 4 — Revised Quest Engine Definition of Done

A quest can be created, opened, started, blocked, updated, abandoned, and completed. Every progress update preserves progress %, notes, session minutes, blocker reason, and timestamp history. Completion requires a result, records optional evidence and actual time, creates a timeline event, and awards immutable XP exactly once inside a database transaction. Duplicate requests cannot award XP twice. Crossing one or more hidden thresholds updates the level and permanently records each level-up event.

## Acceptance checklist

### Quest lifecycle

- [x] Create a quest.
- [x] Click/open a quest.
- [x] Start a quest.
- [x] Block and unblock a quest.
- [x] Abandon a quest.
- [x] Complete a quest.

### Progress history

- [x] Every progress update creates an append-only history record.
- [x] Updates store progress %, notes, session minutes, and timestamp.
- [x] Total actual minutes are accumulated from sessions.
- [x] Estimated vs actual time is visible.

### Completion

- [x] Completion requires a result.
- [x] Optional evidence can be stored.
- [x] Completion timestamp is recorded.
- [x] Completed quest creates a timeline event.

### XP

- [x] XP reward is visible before completion.
- [x] XP is awarded exactly once.
- [x] XP history is immutable.
- [x] DB-level unique event key prevents duplicate XP.
- [x] Quest completion and XP awarding run in one transaction.

### Leveling

- [x] Level thresholds remain hidden.
- [x] A single XP award can cross multiple hidden thresholds.
- [x] Every level-up is recorded in `game_history`.
- [x] Every level-up creates a timeline event.

### AI readiness

- [x] Quests can link to projects or goals.
- [x] Quests store estimated minutes and energy required.
- [x] Quests store source and why/reason fields.
- [x] Completed quests feed the permanent life timeline.
- [x] The daily Director can use open quests as recommendation candidates.

### Tests

- [x] Difficulty reward mapping.
- [x] Single-level and multi-level XP awards.
- [x] Progress history and time accumulation.
- [x] Block/unblock history.
- [x] Result-required completion.
- [x] One-time XP award.
- [x] Timeline event creation.
- [x] Multi-level level-up event creation.
- [x] Validation helpers.
