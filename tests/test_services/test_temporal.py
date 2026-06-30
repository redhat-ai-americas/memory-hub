"""Tests for the temporal classifier and compute_temporal_status helper."""

from datetime import UTC, datetime, timedelta

import pytest

from memoryhub_core.services.temporal import classify_temporal, compute_temporal_status


# -- classify_temporal tests --


class TestExplicitDates:
    """Explicit ISO dates and deadline phrases with dates."""

    def test_standalone_iso_date(self):
        result = classify_temporal("Deploy by 2026-12-31")
        assert result is not None
        assert result.year == 2026
        assert result.month == 12
        assert result.day == 31

    def test_deadline_iso_date(self):
        result = classify_temporal("The deadline is 2027-03-15 for this task")
        assert result is not None
        assert result.year == 2027
        assert result.month == 3
        assert result.day == 15

    def test_due_iso_date(self):
        result = classify_temporal("Report due 2026-08-01")
        assert result is not None
        assert result.year == 2026
        assert result.month == 8
        assert result.day == 1

    def test_before_iso_date(self):
        result = classify_temporal("Must complete before 2026-09-30")
        assert result is not None
        assert result.year == 2026
        assert result.month == 9
        assert result.day == 30

    def test_deadline_natural_date(self):
        now = datetime(2026, 7, 1, tzinfo=UTC)
        result = classify_temporal("Deploy by July 15", created_at=now)
        assert result is not None
        assert result.month == 7
        assert result.day == 15

    def test_deadline_natural_date_with_year(self):
        result = classify_temporal("Complete by March 1, 2027")
        assert result is not None
        assert result.year == 2027
        assert result.month == 3
        assert result.day == 1

    def test_deadline_natural_date_ordinal(self):
        now = datetime(2026, 7, 1, tzinfo=UTC)
        result = classify_temporal("Due December 25th", created_at=now)
        assert result is not None
        assert result.month == 12
        assert result.day == 25


class TestRelativeDeadlines:
    """Relative deadline phrases like 'within N weeks'."""

    def test_within_two_weeks(self):
        now = datetime(2026, 7, 1, tzinfo=UTC)
        result = classify_temporal("Complete within 2 weeks", created_at=now)
        assert result is not None
        assert result == now + timedelta(weeks=2)

    def test_within_three_days(self):
        now = datetime(2026, 7, 1, tzinfo=UTC)
        result = classify_temporal("Fix within 3 days", created_at=now)
        assert result is not None
        assert result == now + timedelta(days=3)

    def test_in_one_month(self):
        now = datetime(2026, 7, 1, tzinfo=UTC)
        result = classify_temporal("Review in 1 month", created_at=now)
        assert result is not None
        assert result == now + timedelta(days=30)

    def test_next_week(self):
        now = datetime(2026, 7, 1, tzinfo=UTC)
        result = classify_temporal("Ship next week", created_at=now)
        assert result is not None
        assert result == now + timedelta(weeks=1)

    def test_next_month(self):
        now = datetime(2026, 7, 1, tzinfo=UTC)
        result = classify_temporal("Revisit next month", created_at=now)
        assert result is not None
        assert result == now + timedelta(days=30)


class TestImplicitTemporal:
    """Implicit temporal markers like 'currently', 'for now'."""

    @pytest.mark.parametrize(
        "content",
        [
            "Currently using FastAPI for the backend",
            "We are right now focused on migration",
            "At the moment, the cluster uses PostgreSQL 15",
            "For now, we deploy to staging only",
            "At present the team uses React 18",
            "For the time being, skip integration tests",
            "Temporarily disabled the rate limiter",
        ],
    )
    def test_implicit_temporal_markers(self, content):
        now = datetime(2026, 7, 1, tzinfo=UTC)
        result = classify_temporal(content, created_at=now)
        assert result is not None
        assert result == now + timedelta(days=90)


class TestEvergreenContent:
    """Content with no temporal signal returns None."""

    @pytest.mark.parametrize(
        "content",
        [
            "User prefers dark mode in all editors",
            "Always use Podman instead of Docker",
            "The project uses PostgreSQL for persistence",
            "Authentication is handled via OAuth2/OIDC",
            "Code reviews require at least one approval",
        ],
    )
    def test_no_temporal_signal(self, content):
        result = classify_temporal(content)
        assert result is None


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_empty_string(self):
        result = classify_temporal("")
        assert result is None

    def test_invalid_iso_date(self):
        # Invalid month/day should not crash
        result = classify_temporal("Deploy by 2026-13-45")
        assert result is None

    def test_deadline_takes_priority_over_standalone(self):
        # "by 2026-07-15" should match deadline pattern, not standalone
        result = classify_temporal("Complete by 2026-07-15 for the release")
        assert result is not None
        assert result.year == 2026
        assert result.month == 7
        assert result.day == 15

    def test_uses_created_at_for_relative(self):
        """Relative deadlines should be computed from created_at, not now()."""
        past = datetime(2020, 1, 1, tzinfo=UTC)
        result = classify_temporal("Complete within 1 week", created_at=past)
        assert result is not None
        assert result == past + timedelta(weeks=1)


# -- compute_temporal_status tests --


class TestComputeTemporalStatus:
    """Tests for the compute_temporal_status helper."""

    def test_none_returns_none(self):
        assert compute_temporal_status(None) is None

    def test_past_returns_expired(self):
        past = datetime(2025, 1, 1, tzinfo=UTC)
        assert compute_temporal_status(past) == "expired"

    def test_far_future_returns_current(self):
        future = datetime(2099, 1, 1, tzinfo=UTC)
        assert compute_temporal_status(future) == "current"

    def test_within_seven_days_returns_expiring_soon(self):
        soon = datetime.now(UTC) + timedelta(days=3)
        assert compute_temporal_status(soon) == "expiring_soon"

    def test_exactly_seven_days_returns_expiring_soon(self):
        # At the boundary: 6.9 days from now should be expiring_soon
        boundary = datetime.now(UTC) + timedelta(days=6, hours=23)
        assert compute_temporal_status(boundary) == "expiring_soon"

    def test_just_past_seven_days_returns_current(self):
        beyond = datetime.now(UTC) + timedelta(days=8)
        assert compute_temporal_status(beyond) == "current"
