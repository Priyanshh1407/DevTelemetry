"""Telemetry ingestion (UPG-02): the one path by which usage data enters the database.

The API (POST /api/ingest) and the simulator (data/seed.py) both use it, so real and
synthetic data get the same validation, the same server-side cost and score, and the same
idempotent upsert. Field names follow Anthropic's usage object (input_tokens = uncached).
"""
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from core.db import rescore
from core.pricing import PRICE_TABLE_VERSION, estimate_cost

MAX_BATCH = 1000
SERVER_COMPUTED = ("estimated_cost_usd", "efficiency_score")


class UsageRecord(BaseModel):
    """One engineer's usage for one day."""
    model_config = ConfigDict(extra="forbid")  # a typo'd field is an error, not silently dropped

    user_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:@-]+$")
    date: date
    name: str | None = Field(default=None, min_length=1, max_length=120)   # required for new engineers
    email: str | None = Field(default=None, min_length=3, max_length=254)
    input_tokens: int = Field(ge=0, description="uncached prompt tokens")
    output_tokens: int = Field(ge=0)
    cache_read_tokens: int = Field(ge=0)
    cache_write_tokens: int = Field(ge=0)
    opus_pct: float = Field(ge=0, le=1)
    sonnet_pct: float = Field(ge=0, le=1)
    haiku_pct: float = Field(ge=0, le=1)
    session_count: int = Field(ge=0)
    compact_uses: int = Field(ge=0)
    git_commits: int = Field(default=0, ge=0)

    @model_validator(mode="before")
    @classmethod
    def _no_client_computed_fields(cls, data):
        if isinstance(data, dict):
            sent = [f for f in SERVER_COMPUTED if f in data]
            if sent:
                raise ValueError(f"{', '.join(sent)} computed by the server; remove from the record")
        return data

    @model_validator(mode="after")
    def _consistent(self):
        shares = self.opus_pct + self.sonnet_pct + self.haiku_pct
        if abs(shares - 1) > 0.02:
            raise ValueError(f"opus_pct + sonnet_pct + haiku_pct must sum to 1 (got {shares:.2f})")
        if self.compact_uses > self.session_count:
            raise ValueError("compact_uses cannot exceed session_count")
        if self.date > datetime.now(timezone.utc).date() + timedelta(days=1):  # 1 day of time-zone slack
            raise ValueError("date is in the future")
        return self


def validate_records(raw_records):
    """Validates each record on its own: returns (valid [(index, UsageRecord)], rejected [...])."""
    valid, rejected, seen = [], [], set()
    for index, raw in enumerate(raw_records):
        user_id = raw.get("user_id") if isinstance(raw, dict) else None
        try:
            rec = UsageRecord.model_validate(raw)
        except ValidationError as e:
            errors = [f"{'.'.join(str(p) for p in err['loc']) or 'record'}: {err['msg']}" for err in e.errors()]
            rejected.append({"index": index, "user_id": user_id, "errors": errors})
            continue
        key = (rec.user_id, rec.date)
        if key in seen:
            rejected.append({"index": index, "user_id": user_id,
                             "errors": ["duplicate user_id/date in this batch"]})
            continue
        seen.add(key)
        valid.append((index, rec))
    return valid, rejected


def upsert_usage(conn, indexed_records):
    """Writes validated records in the caller's transaction. Returns (inserted, updated, rejected).

    Idempotent per (user_id, date): resending a batch updates rows instead of duplicating them.
    Cost and score are always computed here; affected engineers are rescored because the score's
    7-day /compact term depends on neighbouring days.
    """
    if not indexed_records:
        return 0, 0, []
    user_ids = sorted({rec.user_id for _, rec in indexed_records})
    marks = ",".join("?" * len(user_ids))
    known = {r[0] for r in conn.execute(f"SELECT user_id FROM engineers WHERE user_id IN ({marks})", user_ids)}
    existing = {(r[0], r[1]) for r in conn.execute(
        f"SELECT user_id, date FROM usage_metrics WHERE user_id IN ({marks})", user_ids)}

    inserted = updated = 0
    rejected, touched = [], set()
    for index, rec in indexed_records:
        if rec.user_id not in known:
            if not (rec.name and rec.email):
                rejected.append({"index": index, "user_id": rec.user_id,
                                 "errors": ["unknown engineer: include name and email"]})
                continue
            known.add(rec.user_id)
        if rec.name and rec.email:
            conn.execute("""INSERT INTO engineers (user_id, name, email) VALUES (?, ?, ?)
                            ON CONFLICT(user_id) DO UPDATE SET name = excluded.name, email = excluded.email""",
                         (rec.user_id, rec.name, rec.email))

        cost = estimate_cost(rec.input_tokens, rec.output_tokens, rec.cache_read_tokens, rec.cache_write_tokens,
                             {"opus_pct": rec.opus_pct, "sonnet_pct": rec.sonnet_pct, "haiku_pct": rec.haiku_pct})
        day = rec.date.isoformat()
        conn.execute("""
            INSERT INTO usage_metrics (user_id, date, input_tokens, output_tokens, cache_read_tokens,
                cache_write_tokens, opus_pct, sonnet_pct, haiku_pct, session_count, compact_uses, git_commits,
                estimated_cost_usd, cost_price_version, efficiency_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(user_id, date) DO UPDATE SET
                input_tokens = excluded.input_tokens, output_tokens = excluded.output_tokens,
                cache_read_tokens = excluded.cache_read_tokens, cache_write_tokens = excluded.cache_write_tokens,
                opus_pct = excluded.opus_pct, sonnet_pct = excluded.sonnet_pct, haiku_pct = excluded.haiku_pct,
                session_count = excluded.session_count, compact_uses = excluded.compact_uses,
                git_commits = excluded.git_commits, estimated_cost_usd = excluded.estimated_cost_usd,
                cost_price_version = excluded.cost_price_version
        """, (rec.user_id, day, rec.input_tokens, rec.output_tokens, rec.cache_read_tokens, rec.cache_write_tokens,
              rec.opus_pct, rec.sonnet_pct, rec.haiku_pct, rec.session_count, rec.compact_uses, rec.git_commits,
              round(cost, 4), PRICE_TABLE_VERSION))
        if (rec.user_id, day) in existing:
            updated += 1
        else:
            inserted += 1
            existing.add((rec.user_id, day))
        touched.add(rec.user_id)

    rescore(conn, touched)
    return inserted, updated, rejected
