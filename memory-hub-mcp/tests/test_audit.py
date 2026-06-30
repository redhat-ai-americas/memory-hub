"""Tests for audit logging (#67).

Verifies that record_event emits structured JSON to the memoryhub.audit
logger with the expected fields.
"""

import json
import logging

from src.core.audit import record_event


def test_record_event_logs_json(caplog):
    """Basic audit event emits valid JSON with required fields."""
    with caplog.at_level(logging.INFO, logger="memoryhub.audit"):
        record_event(
            event_type="memory.write",
            actor_id="user-1",
            driver_id="user-1",
            scope="user",
            owner_id="user-1",
            memory_id="abc-123",
            decision="allowed",
        )
    assert len(caplog.records) == 1
    event = json.loads(caplog.records[0].message)
    assert event["event_type"] == "memory.write"
    assert event["actor_id"] == "user-1"
    assert event["driver_id"] == "user-1"
    assert event["scope"] == "user"
    assert event["owner_id"] == "user-1"
    assert event["memory_id"] == "abc-123"
    assert event["decision"] == "allowed"
    assert "timestamp" in event


def test_record_event_denied_decision(caplog):
    """Denied decisions are captured with correct actor/driver split."""
    with caplog.at_level(logging.INFO, logger="memoryhub.audit"):
        record_event(
            event_type="memory.write",
            actor_id="user-1",
            driver_id="agent-x",
            scope="project",
            owner_id="proj-1",
            memory_id=None,
            decision="denied",
        )
    event = json.loads(caplog.records[0].message)
    assert event["decision"] == "denied"
    assert event["memory_id"] is None
    assert event["actor_id"] == "user-1"
    assert event["driver_id"] == "agent-x"


def test_record_event_with_metadata(caplog):
    """Optional metadata dict is included when provided."""
    with caplog.at_level(logging.INFO, logger="memoryhub.audit"):
        record_event(
            event_type="memory.search",
            actor_id="user-1",
            driver_id="user-1",
            scope="user",
            owner_id="user-1",
            memory_id=None,
            decision="allowed",
            metadata={"query": "deployment tips", "max_results": 10},
        )
    event = json.loads(caplog.records[0].message)
    assert event["metadata"]["query"] == "deployment tips"
    assert event["metadata"]["max_results"] == 10


def test_record_event_without_metadata(caplog):
    """When metadata is None, the key is absent from the event."""
    with caplog.at_level(logging.INFO, logger="memoryhub.audit"):
        record_event(
            event_type="memory.read",
            actor_id="bot-1",
            driver_id="human-alice",
            scope="user",
            owner_id="human-alice",
            memory_id="def-456",
            decision="allowed",
            metadata=None,
        )
    event = json.loads(caplog.records[0].message)
    assert "metadata" not in event


def test_record_event_session_registered(caplog):
    """Session registration events use scope='session'."""
    with caplog.at_level(logging.INFO, logger="memoryhub.audit"):
        record_event(
            event_type="session.registered",
            actor_id="user-1",
            driver_id="user-1",
            scope="session",
            owner_id="user-1",
            memory_id=None,
            decision="allowed",
            metadata={"auth_method": "api_key", "session_id": "sess-abc"},
        )
    event = json.loads(caplog.records[0].message)
    assert event["event_type"] == "session.registered"
    assert event["scope"] == "session"
    assert event["metadata"]["auth_method"] == "api_key"


def test_record_event_session_denied(caplog):
    """Failed session registration emits a denied event."""
    with caplog.at_level(logging.INFO, logger="memoryhub.audit"):
        record_event(
            event_type="session.denied",
            actor_id="unknown",
            driver_id="unknown",
            scope="session",
            owner_id="unknown",
            memory_id=None,
            decision="denied",
            metadata={"auth_method": "api_key"},
        )
    event = json.loads(caplog.records[0].message)
    assert event["event_type"] == "session.denied"
    assert event["decision"] == "denied"
