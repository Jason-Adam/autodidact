"""SQLite learning database with FTS5 full-text search.

All knowledge captured by autodidact hooks flows through this module.
Uses only Python stdlib (sqlite3). DB stored at ~/.claude/autodidact/learning.db.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.confidence import (
    BOOST_DEFAULT,
    CONFIDENCE_FLOOR,
    CONFIDENCE_MIN,
    DECAY_DEFAULT,
    GRADUATION_CONFIDENCE,
    GRADUATION_MIN_OBSERVATIONS,
    PRUNE_CONFIDENCE,
    PRUNE_MAX_AGE_DAYS,
    TIME_DECAY_RATE,
)

DEFAULT_DB_PATH = Path.home() / ".claude" / "autodidact" / "learning.db"

SCHEMA_VERSION = 3

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS learnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    confidence REAL DEFAULT 0.5,
    tags TEXT DEFAULT '',
    source TEXT DEFAULT '',
    project_path TEXT DEFAULT '',
    session_id TEXT DEFAULT '',
    observation_count INTEGER DEFAULT 1,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    graduated_to TEXT DEFAULT '',
    error_signature TEXT DEFAULT '',
    error_type TEXT DEFAULT '',
    fix_type TEXT DEFAULT '',
    fix_action TEXT DEFAULT '',
    UNIQUE(topic, key)
);

CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(
    topic, key, value, tags, error_signature,
    content='learnings',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS learnings_ai AFTER INSERT ON learnings BEGIN
    INSERT INTO learnings_fts(rowid, topic, key, value, tags, error_signature)
    VALUES (new.id, new.topic, new.key, new.value, new.tags, new.error_signature);
END;

CREATE TRIGGER IF NOT EXISTS learnings_ad AFTER DELETE ON learnings BEGIN
    INSERT INTO learnings_fts(learnings_fts, rowid, topic, key, value, tags, error_signature)
    VALUES ('delete', old.id, old.topic, old.key, old.value, old.tags, old.error_signature);
END;

CREATE TRIGGER IF NOT EXISTS learnings_au AFTER UPDATE ON learnings BEGIN
    INSERT INTO learnings_fts(learnings_fts, rowid, topic, key, value, tags, error_signature)
    VALUES ('delete', old.id, old.topic, old.key, old.value, old.tags, old.error_signature);
    INSERT INTO learnings_fts(rowid, topic, key, value, tags, error_signature)
    VALUES (new.id, new.topic, new.key, new.value, new.tags, new.error_signature);
END;

CREATE TABLE IF NOT EXISTS routing_gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt TEXT NOT NULL,
    attempted_tiers TEXT NOT NULL,
    final_classification TEXT DEFAULT '',
    timestamp TEXT NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class LearningDB:
    """Manages the autodidact learning database."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 1:
            self.conn.executescript(_SCHEMA_V1)
            self.conn.execute("PRAGMA user_version = 1")
            self.conn.commit()
            version = 1
        if version < 2:
            self.conn.execute("ALTER TABLE learnings ADD COLUMN access_count INTEGER DEFAULT 0")
            self.conn.execute("ALTER TABLE learnings ADD COLUMN outcome TEXT DEFAULT ''")
            self.conn.execute("PRAGMA user_version = 2")
            self.conn.commit()
            version = 2
        if version < 3:
            self.conn.execute(
                "ALTER TABLE learnings ADD COLUMN last_accessed_session TEXT DEFAULT ''"
            )
            self.conn.execute("PRAGMA user_version = 3")
            self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> LearningDB:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    # ── Record ──────────────────────────────────────────────────────────

    def record(
        self,
        topic: str,
        key: str,
        value: str,
        *,
        category: str = "general",
        confidence: float = 0.5,
        tags: str = "",
        source: str = "",
        project_path: str = "",
        session_id: str = "",
        error_signature: str = "",
        error_type: str = "",
        fix_type: str = "",
        fix_action: str = "",
        outcome: str = "",
    ) -> int:
        """Record a new learning or update an existing one (upsert on topic+key)."""
        now = _now_iso()
        cursor = self.conn.execute(
            """
            INSERT INTO learnings (
                topic, key, value, category, confidence, tags, source,
                project_path, session_id, observation_count,
                first_seen, last_seen,
                error_signature, error_type, fix_type, fix_action, outcome
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(topic, key) DO UPDATE SET
                value = excluded.value,
                confidence = MAX(confidence, excluded.confidence),
                tags = CASE WHEN excluded.tags != '' THEN excluded.tags ELSE tags END,
                source = CASE WHEN excluded.source != '' THEN excluded.source ELSE source END,
                observation_count = observation_count + 1,
                last_seen = excluded.last_seen,
                error_signature = CASE WHEN excluded.error_signature != ''
                    THEN excluded.error_signature ELSE error_signature END,
                fix_type = CASE WHEN excluded.fix_type != ''
                    THEN excluded.fix_type ELSE fix_type END,
                fix_action = CASE WHEN excluded.fix_action != ''
                    THEN excluded.fix_action ELSE fix_action END,
                outcome = CASE WHEN excluded.outcome != '' THEN excluded.outcome ELSE outcome END
            """,
            (
                topic,
                key,
                value,
                category,
                confidence,
                tags,
                source,
                project_path,
                session_id,
                now,
                now,
                error_signature,
                error_type,
                fix_type,
                fix_action,
                outcome,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid or 0

    # ── Query ───────────────────────────────────────────────────────────

    def query_fts(
        self,
        search_text: str,
        *,
        limit: int = 5,
        min_confidence: float = 0.3,
    ) -> list[dict[str, Any]]:
        """Full-text search against learnings. Returns dicts sorted by relevance."""
        if not search_text.strip():
            return []
        # Sanitize for FTS5: remove special chars that break queries
        safe_text = "".join(c if c.isalnum() or c.isspace() else " " for c in search_text)
        tokens = safe_text.split()
        if not tokens:
            return []
        # Use OR matching for broader recall
        fts_query = " OR ".join(tokens[:10])  # cap at 10 terms
        rows = self.conn.execute(
            """
            SELECT l.*, rank
            FROM learnings_fts fts
            JOIN learnings l ON l.id = fts.rowid
            WHERE learnings_fts MATCH ?
              AND l.confidence >= ?
              AND l.graduated_to = ''
            ORDER BY (rank - (l.access_count * 0.1))
            LIMIT ?
            """,
            (fts_query, min_confidence, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def increment_access(self, learning_id: int, session_id: str = "") -> None:
        """Increment access counter when a learning is injected into a session."""
        self.conn.execute(
            """UPDATE learnings
            SET access_count = access_count + 1,
                last_seen = ?,
                last_accessed_session = ?
            WHERE id = ?""",
            (_now_iso(), session_id, learning_id),
        )
        self.conn.commit()

    def get_by_id(self, learning_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM learnings WHERE id = ?", (learning_id,)).fetchone()
        return dict(row) if row else None

    def get_by_error_signature(self, signature: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM learnings WHERE error_signature = ? ORDER BY confidence DESC LIMIT 1",
            (signature,),
        ).fetchone()
        return dict(row) if row else None

    def get_top_learnings(
        self,
        *,
        limit: int = 10,
        project_path: str = "",
    ) -> list[dict[str, Any]]:
        """Get highest-confidence non-graduated learnings."""
        if project_path:
            rows = self.conn.execute(
                """
                SELECT * FROM learnings
                WHERE graduated_to = ''
                  AND (project_path = ? OR project_path = '')
                ORDER BY confidence DESC
                LIMIT ?
                """,
                (project_path, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM learnings
                WHERE graduated_to = ''
                ORDER BY confidence DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_progressive_learnings(
        self,
        *,
        token_budget: int = 2000,
        project_path: str = "",
        topic_hint: str = "",
        min_confidence: float = 0.3,
    ) -> dict[str, list[dict[str, Any]]]:
        """Token-budgeted progressive learning injection.

        Returns two tiers:
          - "core": highest-confidence learnings (always included first)
          - "relevant": FTS5 topic-matched learnings (fills remaining budget)

        Token estimation: len(value) // 4 (rough chars-to-tokens).
        """
        # Overfetch for selection pool
        pool = self.get_top_learnings(limit=20, project_path=project_path)
        pool = [e for e in pool if e["confidence"] >= min_confidence]

        core: list[dict[str, Any]] = []
        tokens_used = 0
        half_budget = token_budget // 2

        for entry in pool:
            entry_tokens = len(entry["value"]) // 4 + 20
            if tokens_used + entry_tokens > half_budget or len(core) >= 7:
                break
            core.append(entry)
            tokens_used += entry_tokens

        # Topic-relevant tier via FTS5
        relevant: list[dict[str, Any]] = []
        if topic_hint:
            core_ids = {e["id"] for e in core}
            fts_results = self.query_fts(topic_hint, limit=10, min_confidence=min_confidence)
            for entry in fts_results:
                if entry["id"] in core_ids:
                    continue
                entry_tokens = len(entry["value"]) // 4 + 20
                if tokens_used + entry_tokens > token_budget:
                    break
                relevant.append(entry)
                tokens_used += entry_tokens

        return {"core": core, "relevant": relevant}

    # ── Confidence ──────────────────────────────────────────────────────

    def boost(self, learning_id: int, amount: float = BOOST_DEFAULT) -> None:
        self.conn.execute(
            """
            UPDATE learnings
            SET confidence = MIN(confidence + ?, 1.0),
                observation_count = observation_count + 1,
                success_count = success_count + 1,
                last_seen = ?
            WHERE id = ?
            """,
            (amount, _now_iso(), learning_id),
        )
        self.conn.commit()

    def decay(self, learning_id: int, amount: float = DECAY_DEFAULT) -> None:
        self.conn.execute(
            """
            UPDATE learnings
            SET confidence = MAX(confidence - ?, ?),
                observation_count = observation_count + 1,
                failure_count = failure_count + 1,
                last_seen = ?
            WHERE id = ?
            """,
            (amount, CONFIDENCE_MIN, _now_iso(), learning_id),
        )
        self.conn.commit()

    def time_decay(self, learning_ids: list[int], rate: float = TIME_DECAY_RATE) -> None:
        """Apply time-based decay. Called on session Stop."""
        now = datetime.now(UTC)
        for lid in learning_ids:
            row = self.conn.execute(
                "SELECT last_seen, confidence FROM learnings WHERE id = ?",
                (lid,),
            ).fetchone()
            if not row:
                continue
            last_seen = datetime.fromisoformat(row["last_seen"])
            # Normalize timezone: make both aware or both naive
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=UTC)
            days = (now - last_seen).days
            if days <= 0:
                continue
            decay_amount = days * rate
            new_confidence = max(row["confidence"] - decay_amount, CONFIDENCE_FLOOR)
            self.conn.execute(
                "UPDATE learnings SET confidence = ? WHERE id = ?",
                (new_confidence, lid),
            )
        self.conn.commit()

    # ── Graduation ──────────────────────────────────────────────────────

    def graduate(self, learning_id: int, destination_path: str) -> bool:
        """Mark a learning as graduated to a file. Returns True if eligible."""
        row = self.get_by_id(learning_id)
        if not row:
            return False
        if (
            row["confidence"] < GRADUATION_CONFIDENCE
            or row["observation_count"] < GRADUATION_MIN_OBSERVATIONS
        ):
            return False
        self.conn.execute(
            "UPDATE learnings SET graduated_to = ? WHERE id = ?",
            (destination_path, learning_id),
        )
        self.conn.commit()
        return True

    def get_graduation_candidates(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM learnings
            WHERE graduated_to = ''
              AND confidence >= ?
              AND observation_count >= ?
            ORDER BY confidence DESC, observation_count DESC
            """,
            (GRADUATION_CONFIDENCE, GRADUATION_MIN_OBSERVATIONS),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Prune ───────────────────────────────────────────────────────────

    def prune(
        self,
        *,
        max_age_days: int = PRUNE_MAX_AGE_DAYS,
        min_confidence: float = PRUNE_CONFIDENCE,
    ) -> int:
        """Delete stale low-confidence learnings. Returns count deleted."""
        cutoff = datetime.now(UTC)
        cursor = self.conn.execute(
            """
            DELETE FROM learnings
            WHERE confidence < ?
              AND julianday(?) - julianday(last_seen) > ?
            """,
            (min_confidence, cutoff.isoformat(), max_age_days),
        )
        self.conn.commit()
        return cursor.rowcount

    # ── Routing Gaps ────────────────────────────────────────────────────

    def record_routing_gap(
        self,
        prompt: str,
        tiers: list[int | float],
        classification: str = "",
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO routing_gaps (prompt, attempted_tiers, final_classification, timestamp)
            VALUES (?, ?, ?, ?)
            """,
            (prompt, json.dumps(tiers), classification, _now_iso()),
        )
        self.conn.commit()
        return cursor.lastrowid or 0

    def get_routing_gaps(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM routing_gaps ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Stats ───────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        row = self.conn.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN graduated_to != '' THEN 1 ELSE 0 END) as graduated,
                AVG(confidence) as avg_confidence,
                SUM(observation_count) as total_observations,
                SUM(success_count) as total_successes,
                SUM(failure_count) as total_failures
            FROM learnings
            """
        ).fetchone()
        return dict(row) if row else {}

    def set_outcome(self, learning_id: int, outcome: str) -> None:
        """Update the outcome field on a learning."""
        self.conn.execute(
            "UPDATE learnings SET outcome = ?, last_seen = ? WHERE id = ?",
            (outcome, _now_iso(), learning_id),
        )
        self.conn.commit()

    def get_accessed_in_session(self, session_id: str) -> list[dict[str, Any]]:
        """Get learnings that were accessed (injected) during a session."""
        rows = self.conn.execute(
            "SELECT * FROM learnings WHERE last_accessed_session = ? AND access_count > 0",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_by_outcome(self, outcome: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Query learnings by outcome category."""
        rows = self.conn.execute(
            "SELECT * FROM learnings WHERE outcome = ? ORDER BY confidence DESC LIMIT ?",
            (outcome, limit),
        ).fetchall()
        return [dict(r) for r in rows]
