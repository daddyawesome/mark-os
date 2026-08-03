from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


CREATION_FINGERPRINT_FIELDS = (
    "dedupe_key",
    "company",
    "contact_person",
    "job_title",
    "source",
    "source_url",
    "problem_opportunity",
    "why_mark_fits",
    "pipeline_status",
    "priority",
    "next_action",
    "next_action_due_date",
    "notes",
)


def lead_creation_fingerprint(values: Mapping[str, str | None]) -> str:
    """Return the versioned fingerprint shared by lead writes and migrations."""
    serialized = json.dumps(
        [values[field] for field in CREATION_FINGERPRINT_FIELDS],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"v1:{digest}"
