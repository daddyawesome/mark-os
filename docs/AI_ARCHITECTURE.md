# MARK OS Budget-Safe AI Chat Architecture

Planned milestone: **v0.2.2**, immediately after the interactive Quest Engine.

## Core rule

MARK OS owns its memory. The AI API receives only a small, purpose-built context packet.

```text
User message
    ↓
Save user message to SQLite
    ↓
Fetch up to 10 recent chat messages
    + compact system state
    + latest check-in
    + active quests
    + a few relevant long-term memories
    ↓
Trim to a hard token budget
    ↓
Call budget model with store=False
    ↓
Save assistant response + token usage + estimated cost
    ↓
Optionally extract durable memory / quest suggestion
    ↓
Archive old raw chat only after summarization
```

## Why "up to 10", not "at least 10"

A budget cap must be an upper bound. If the conversation is short, send fewer messages. If messages are long, trim by token budget before the API call.

## Context packet

The default chat request should include only:

1. System identity and safety rules.
2. User profile summary.
3. Current Level and tracked XP.
4. Latest check-in.
5. Up to 8 active quests.
6. Up to 6 relevant memories or timeline events.
7. Up to 10 recent chat messages.
8. The new user message.

The full SQLite history is never sent on every turn.

## Storage strategy

Keep these as separate layers:

- `chat_messages`: recent raw conversation.
- `chat_summaries`: compressed older conversation windows.
- `memories`: durable facts, preferences, lessons, and constraints.
- `timeline_events`: meaningful life events.
- `tasks`: quests and work state.
- `ai_usage`: model, input tokens, output tokens, estimated cost, latency.

Do not delete meaningful life history just to keep the database tiny. SQLite can hold far more text than MARK OS will generate at this stage. Archive and summarize raw chat instead.

## Model routing

Default routine chat:

- `gpt-5.4-nano`

Escalate only for harder work:

- `gpt-5.4-mini`

Examples of escalation:

- weekly review;
- conflicting goals;
- strategy decisions;
- ambiguous recommendations;
- user explicitly chooses a deeper mode.

## Cost controls

- hard maximum input context;
- hard maximum output tokens;
- daily request cap;
- daily and monthly application-side spend cap;
- no automatic retries beyond one controlled fallback;
- save usage for every API response;
- use `store=False` because MARK OS owns the conversation database;
- do not chain unlimited remote conversation state.

## Future tool permissions

Read automatically:

- profile;
- goals;
- quests;
- memories;
- check-ins;
- calendar summaries;
- GitHub activity summaries.

Require explicit confirmation before:

- completing a quest;
- awarding manual XP;
- sending email;
- deleting data;
- spending money;
- changing important goals.
