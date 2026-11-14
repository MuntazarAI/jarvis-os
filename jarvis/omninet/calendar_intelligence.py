"""
Calendar Intelligence — JARVIS-OS OMNINET subsystem.

Provides schedule management, meeting coordination, and reminder tracking.
Read-only by default — no calendar modification without explicit PolicyEngine
grant.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..core.logging import get_module_logger
from ..policy.policy import PolicyEngine
from ..events.store import EventStore

log = get_module_logger(__name__)


@dataclass
class CalendarEvent:
    """A calendar event."""
    event_id: str
    title: str
    description: str
    start_time: float
    end_time: float
    location: str
    attendees: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass
class MeetingRequest:
    """A meeting coordination request."""
    request_id: str
    organizer: str
    participants: list[str]
    proposed_times: list[float]
    duration_minutes: int
    status: str = "pending"  # pending, accepted, declined, cancelled
    timestamp: float = field(default_factory=time.time)


@dataclass
class Reminder:
    """A reminder."""
    reminder_id: str
    title: str
    due_time: float
    completed: bool = False
    timestamp: float = field(default_factory=time.time)


class CalendarIntelligence:
    """
    Calendar Intelligence — schedule management, meeting coordination,
    and reminder tracking.

    Read-only by default. Calendar modification requires explicit PolicyEngine
    grant. No automated scheduling without approval.
    """

    def __init__(
        self,
        policy: PolicyEngine | None = None,
        events: EventStore | None = None,
    ) -> None:
        self.policy = policy
        self.events = events
        self.calendar_events: dict[str, CalendarEvent] = {}
        self.meeting_requests: dict[str, MeetingRequest] = {}
        self.reminders: dict[str, Reminder] = {}
        self._initialized = False

    def initialize(self) -> dict[str, Any]:
        """Initialize the calendar intelligence subsystem."""
        self._initialized = True
        return {
            "status": "operational",
            "subsystem": "calendar_intelligence",
            "policy_gated": True,
            "read_only_default": True,
        }

    def get_events(
        self,
        start_time: float,
        end_time: float,
    ) -> list[CalendarEvent]:
        """Get calendar events in a time range."""
        matching = [
            e for e in self.calendar_events.values()
            if start_time <= e.start_time <= end_time
        ]
        return sorted(matching, key=lambda e: e.start_time)

    def create_event(
        self,
        title: str,
        description: str,
        start_time: float,
        end_time: float,
        location: str = "",
    ) -> dict[str, Any]:
        """Create a calendar event (requires PolicyEngine grant)."""
        grant_result = {"approved": False, "reason": "no policy engine"}
        if self.policy:
            grant_result = self.policy.evaluate(
                "calendar_intelligence.create_event",
                {
                    "title": title,
                    "start_time": start_time,
                    "end_time": end_time,
                },
            )

        if not grant_result.get("approved", False):
            return {"ok": False, "reason": "policy denied"}

        event = CalendarEvent(
            event_id=f"cal-{int(time.time() * 1000)}",
            title=title,
            description=description,
            start_time=start_time,
            end_time=end_time,
            location=location,
        )
        self.calendar_events[event.event_id] = event

        if self.events:
            self.events.append({
                "event": "calendar_intelligence.create_event",
                "event_id": event.event_id,
                "title": title,
                "at": event.timestamp,
            })

        return {"ok": True, "event_id": event.event_id}

    def create_meeting_request(
        self,
        organizer: str,
        participants: list[str],
        proposed_times: list[float],
        duration_minutes: int,
    ) -> MeetingRequest:
        """Create a meeting coordination request."""
        req = MeetingRequest(
            request_id=f"meet-{int(time.time() * 1000)}",
            organizer=organizer,
            participants=participants,
            proposed_times=proposed_times,
            duration_minutes=duration_minutes,
        )
        self.meeting_requests[req.request_id] = req
        return req

    def create_reminder(
        self,
        title: str,
        due_time: float,
    ) -> Reminder:
        """Create a reminder."""
        reminder = Reminder(
            reminder_id=f"rem-{int(time.time() * 1000)}",
            title=title,
            due_time=due_time,
        )
        self.reminders[reminder.reminder_id] = reminder
        return reminder

    def get_status(self) -> dict[str, Any]:
        """Get subsystem status."""
        return {
            "subsystem": "calendar_intelligence",
            "status": "operational" if self._initialized else "offline",
            "calendar_events": len(self.calendar_events),
            "meeting_requests": len(self.meeting_requests),
            "reminders": len(self.reminders),
            "capabilities": [
                "calendar_query",
                "event_creation",
                "meeting_coordination",
                "reminder_tracking",
            ],
            "constraints": [
                "calendar_modification_requires_policy_grant",
                "no_automated_scheduling_without_approval",
                "read_only_default",
            ],
        }


# Global instance
_calendar: CalendarIntelligence | None = None


def get_calendar_intelligence(
    policy: PolicyEngine | None = None,
    events: EventStore | None = None,
) -> CalendarIntelligence:
    """Get or create the global Calendar Intelligence instance."""
    global _calendar
    if _calendar is None:
        _calendar = CalendarIntelligence(policy=policy, events=events)
    return _calendar


__all__ = [
    "CalendarIntelligence",
    "CalendarEvent",
    "MeetingRequest",
    "Reminder",
    "get_calendar_intelligence",
]