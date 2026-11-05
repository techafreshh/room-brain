"""Deterministic demo week: 7 days of decisions, live and local modes.

The week is hard-coded (no LLM, no network at build time) so a fresh
checkout seeds reproducibly. Every entry is kind="decision" with a
backdated ISO timestamp; at least five entries carry the contiguous
phrase "seeded topic" so keyword recall finds them.

Local mode writes synthetic thread ids (``synth-<room>-<n>``) and never
touches the network. Live mode posts each entry text through the Switch
``post_message`` op and stores the real returned id as thread_id.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import roombrain.agent.ops as ops

ROOM_LAUNCH = "#launch"
ROOM_PLATFORM = "#platform"
ROOM_GROWTH = "#growth"


def _at(days_ago, hour, minute):
    """ISO timestamp for a fixed wall-clock time a number of days ago."""
    base = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()


def build_week():
    """Return the 24-entry demo week (no DB or network side effects)."""
    return [
        {
            "text": "Decision: launch checklist frozen, seeded topic pricing "
            "review agreed at standup, copy locked Thursday",
            "room": ROOM_LAUNCH, "actor": "@ana:sw",
            "timestamp": _at(6, 9, 5), "kind": "decision", "confidence": 0.9,
        },
        {
            "text": "Decision: Postgres pool raised to 50 connections, "
            "pgbouncer stays in transaction mode",
            "room": ROOM_PLATFORM, "actor": "@ben:sw",
            "timestamp": _at(6, 13, 20), "kind": "decision", "confidence": 0.8,
        },
        {
            "text": "Decision: onboarding email 2 rewritten, trial-to-paid "
            "nudge moves to day 5",
            "room": ROOM_GROWTH, "actor": "@cara:sw",
            "timestamp": _at(6, 16, 45), "kind": "decision", "confidence": 0.8,
        },
        {
            "text": "Decision: seeded topic launch retro, Thursday ship date "
            "confirmed, rollback plan assigned to Ben",
            "room": ROOM_LAUNCH, "actor": "@dev:sw",
            "timestamp": _at(5, 9, 10), "kind": "decision", "confidence": 0.9,
        },
        {
            "text": "Decision: API limit 100 req/s per key with exponential "
            "backoff, 429s carry Retry-After headers",
            "room": ROOM_PLATFORM, "actor": "@ana:sw",
            "timestamp": _at(5, 12, 30), "kind": "decision", "confidence": 0.85,
        },
        {
            "text": "Decision: referral bonus doubled to $25 credit through "
            "end of month",
            "room": ROOM_GROWTH, "actor": "@ben:sw",
            "timestamp": _at(5, 15, 15), "kind": "decision", "confidence": 0.7,
        },
        {
            "text": "Decision: homepage hero swaps to a customer quote, "
            "signup button stays above the fold",
            "room": ROOM_LAUNCH, "actor": "@cara:sw",
            "timestamp": _at(4, 10, 0), "kind": "decision", "confidence": 0.75,
        },
        {
            "text": "Decision: deploy freeze every Friday from 15:00 UTC, "
            "hotfixes need two approvals",
            "room": ROOM_PLATFORM, "actor": "@dev:sw",
            "timestamp": _at(4, 14, 0), "kind": "decision", "confidence": 0.9,
        },
        {
            "text": "Decision: seeded topic onboarding checklist shortened "
            "to 3 steps, invite-teammates prompt stays",
            "room": ROOM_GROWTH, "actor": "@ana:sw",
            "timestamp": _at(4, 16, 30), "kind": "decision", "confidence": 0.8,
        },
        {
            "text": "Decision: seeded topic refund policy, 30-day "
            "no-questions refunds, support macro updated",
            "room": ROOM_LAUNCH, "actor": "@ben:sw",
            "timestamp": _at(3, 9, 30), "kind": "decision", "confidence": 0.9,
        },
        {
            "text": "Decision: Redis TTL for session tokens cut to 15 "
            "minutes after the stale-auth incident",
            "room": ROOM_PLATFORM, "actor": "@cara:sw",
            "timestamp": _at(3, 11, 45), "kind": "decision", "confidence": 0.85,
        },
        {
            "text": "Decision: weekly changelog email moves to Tuesday "
            "mornings, open rate was 12 points higher",
            "room": ROOM_GROWTH, "actor": "@dev:sw",
            "timestamp": _at(3, 15, 0), "kind": "decision", "confidence": 0.7,
        },
        {
            "text": "Decision: beta cohort capped at 200 workspaces, "
            "waitlist messaging goes live tomorrow",
            "room": ROOM_LAUNCH, "actor": "@ana:sw",
            "timestamp": _at(2, 9, 15), "kind": "decision", "confidence": 0.8,
        },
        {
            "text": "Decision: seeded topic deploy pipeline, migrations run "
            "before web rollout, verify job blocks traffic shift",
            "room": ROOM_PLATFORM, "actor": "@ben:sw",
            "timestamp": _at(2, 12, 0), "kind": "decision", "confidence": 0.9,
        },
        {
            "text": "Decision: seeded topic discount pilot, 20% annual-plan "
            "coupon for education accounts capped at 500 redemptions",
            "room": ROOM_GROWTH, "actor": "@cara:sw",
            "timestamp": _at(2, 16, 0), "kind": "decision", "confidence": 0.75,
        },
        {
            "text": "Decision: status page launches with the release, "
            "incident template assigned to Ana",
            "room": ROOM_LAUNCH, "actor": "@dev:sw",
            "timestamp": _at(1, 10, 20), "kind": "decision", "confidence": 0.85,
        },
        {
            "text": "Decision: seeded topic incident review, cache stampede "
            "traced to thundering retries, jitter added",
            "room": ROOM_PLATFORM, "actor": "@ana:sw",
            "timestamp": _at(1, 13, 10), "kind": "decision", "confidence": 0.9,
        },
        {
            "text": "Decision: ad spend shifts 60% to search and 40% to "
            "social after the CAC comparison",
            "room": ROOM_GROWTH, "actor": "@ben:sw",
            "timestamp": _at(1, 15, 40), "kind": "decision", "confidence": 0.7,
        },
        {
            "text": "Decision: launch day war room opens 08:00 UTC, go/no-go "
            "call at 09:30 sharp",
            "room": ROOM_LAUNCH, "actor": "@cara:sw",
            "timestamp": _at(0, 9, 5), "kind": "decision", "confidence": 0.9,
        },
        {
            "text": "Decision: seeded topic weekly retro, deploys cut from "
            "40 to 12 minutes, flaky test quarantined",
            "room": ROOM_PLATFORM, "actor": "@dev:sw",
            "timestamp": _at(0, 11, 30), "kind": "decision", "confidence": 0.85,
        },
        {
            "text": "Decision: pricing experiment starts Monday, monthly vs "
            "annual toggle default flips to annual",
            "room": ROOM_GROWTH, "actor": "@ana:sw",
            "timestamp": _at(0, 14, 15), "kind": "decision", "confidence": 0.8,
        },
        {
            "text": "Decision: press embargo lifts Thursday 13:00 UTC, "
            "quotes approved by founders only",
            "room": ROOM_LAUNCH, "actor": "@ben:sw",
            "timestamp": _at(1, 17, 0), "kind": "decision", "confidence": 0.8,
        },
        {
            "text": "Decision: database backup restores drilled weekly, "
            "last drill recovered in 11 minutes",
            "room": ROOM_PLATFORM, "actor": "@cara:sw",
            "timestamp": _at(0, 15, 30), "kind": "decision", "confidence": 0.85,
        },
        {
            "text": "Decision: community office hours move to Fridays, "
            "recordings posted within 24 hours",
            "room": ROOM_GROWTH, "actor": "@dev:sw",
            "timestamp": _at(0, 16, 45), "kind": "decision", "confidence": 0.7,
        },
    ]


def _local_thread_id(room, index):
    slug = (room or "").lstrip("#").strip().lower().replace(" ", "-")
    return "synth-%s-%d" % (slug or "room", index)


def seed_local(db_path=None):
    """Write the demo week with synthetic thread ids; return the count."""
    from memory.vault import upsert_memory

    count = 0
    for index, entry in enumerate(build_week(), start=1):
        upsert_memory(
            entry["text"],
            entry["room"],
            entry["actor"],
            _local_thread_id(entry["room"], index),
            entry["kind"],
            entry["confidence"],
            timestamp=entry["timestamp"],
            db_path=db_path,
        )
        count += 1
    return count


def _coerce_thread_id(result, fallback):
    """Adopt a post_message result id, else the live-<n> fallback."""
    if isinstance(result, str) and result.strip():
        return result.strip()
    if isinstance(result, dict):
        for key in ("message_id", "thread_id", "id"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("message", "result"):
            nested = result.get(key)
            if isinstance(nested, dict):
                for inner in ("message_id", "thread_id", "id"):
                    value = nested.get(inner)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
    return fallback


def _room_list(rooms):
    if isinstance(rooms, (list, tuple)):
        return [str(room).strip() for room in rooms if str(room).strip()]
    if isinstance(rooms, str):
        return [part.strip() for part in rooms.split(",") if part.strip()]
    return []


def seed_live(server, agent_id, api_key, connection_id, rooms="",
              db_path=None, client=None):
    """Post the demo week via post_message; store real ids as thread_id."""
    from memory.vault import upsert_memory

    targets = _room_list(rooms)
    count = 0
    for index, entry in enumerate(build_week(), start=1):
        room_id = targets[(index - 1) % len(targets)] if targets else entry["room"]
        result = ops.post_message(
            server, agent_id, api_key, connection_id,
            room_id, entry["text"], client=client,
        )
        thread_id = _coerce_thread_id(result, "live-%d" % index)
        upsert_memory(
            entry["text"],
            entry["room"],
            entry["actor"],
            thread_id,
            entry["kind"],
            entry["confidence"],
            timestamp=entry["timestamp"],
            db_path=db_path,
        )
        count += 1
    return count
