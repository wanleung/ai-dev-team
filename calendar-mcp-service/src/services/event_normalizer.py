"""Event normalizer service.

Converts between provider-specific event representations and the unified
internal event model.
"""

import logging
from datetime import datetime
from typing import Any, Optional

from src.models.calendar import Event, EventAttendee, EventReminder, RecurrenceRule

logger = logging.getLogger(__name__)


class EventNormalizer:
    """Normalizes events between provider-specific and unified formats.
    
    Handles conversion of provider-specific event representations to and from
    the unified Event model used throughout the application.
    """
    
    def normalize_event(self, provider: str, raw_event: dict[str, Any]) -> Event:
        """Convert a provider-specific event to the unified Event model.
        
        Args:
            provider: Provider name ('google' or 'outlook').
            raw_event: Raw event dictionary from provider API.
            
        Returns:
            Unified Event object.
        """
        if provider == "google":
            return self._normalize_google_event(raw_event)
        elif provider == "outlook":
            return self._normalize_outlook_event(raw_event)
        else:
            raise ValueError(f"Unknown provider: {provider}")
    
    def denormalize_event(self, provider: str, unified_event: Event) -> dict[str, Any]:
        """Convert a unified Event to provider-specific format.
        
        Args:
            provider: Provider name ('google' or 'outlook').
            unified_event: Unified Event object.
            
        Returns:
            Provider-specific event dictionary.
        """
        if provider == "google":
            return self._denormalize_google_event(unified_event)
        elif provider == "outlook":
            return self._denormalize_outlook_event(unified_event)
        else:
            raise ValueError(f"Unknown provider: {provider}")
    
    def _normalize_google_event(self, raw_event: dict[str, Any]) -> Event:
        """Normalize a Google Calendar event.
        
        Args:
            raw_event: Raw Google Calendar API event.
            
        Returns:
            Unified Event object.
        """
        start_info = raw_event.get("start", {})
        end_info = raw_event.get("end", {})
        
        start_dt = self._parse_datetime(start_info.get("dateTime") or start_info.get("date"))
        end_dt = self._parse_datetime(end_info.get("dateTime") or end_info.get("date"))
        timezone = start_info.get("timeZone", "UTC")
        
        attendees = []
        for att in raw_event.get("attendees", []):
            attendees.append(EventAttendee(
                email=att.get("email", ""),
                name=att.get("displayName"),
                response_status=att.get("responseStatus"),
                is_organizer=att.get("organizer", False),
            ))
        
        reminders = []
        for rem in raw_event.get("reminders", {}).get("overrides", []):
            reminders.append(EventReminder(
                method=rem.get("method", "popup"),
                minutes_before=rem.get("minutes", 0),
            ))
        
        recurrence = None
        if raw_event.get("recurrence"):
            recurrence = self._parse_recurrence_rules(raw_event["recurrence"])
        
        return Event(
            id=raw_event["id"],
            calendar_id=raw_event.get("calendar_id", ""),
            title=raw_event.get("summary", ""),
            description=raw_event.get("description"),
            location=raw_event.get("location"),
            start=start_dt,
            end=end_dt,
            timezone=timezone,
            attendees=attendees,
            reminders=reminders,
            recurrence=recurrence,
            status=raw_event.get("status", "confirmed"),
            created_at=self._parse_datetime(raw_event.get("created")),
            updated_at=self._parse_datetime(raw_event.get("updated")),
            etag=raw_event.get("etag"),
            is_recurring_master=bool(raw_event.get("recurrence")),
            recurrence_id=raw_event.get("recurringEventId"),
            provider_metadata={"htmlLink": raw_event.get("htmlLink")},
        )
    
    def _normalize_outlook_event(self, raw_event: dict[str, Any]) -> Event:
        """Normalize an Outlook Calendar event.
        
        Args:
            raw_event: Raw Microsoft Graph API event.
            
        Returns:
            Unified Event object.
        """
        start_info = raw_event.get("start", {})
        end_info = raw_event.get("end", {})
        
        start_dt = self._parse_datetime(start_info.get("dateTime"))
        end_dt = self._parse_datetime(end_info.get("dateTime"))
        timezone = start_info.get("timeZone", "UTC")
        
        attendees = []
        for att in raw_event.get("attendees", []):
            email_addr = att.get("emailAddress", {})
            attendees.append(EventAttendee(
                email=email_addr.get("address", ""),
                name=email_addr.get("name"),
                response_status=att.get("status", {}).get("response"),
                is_organizer=False,
            ))
        
        reminders = []
        if raw_event.get("isReminderOn"):
            reminders.append(EventReminder(
                method="popup",
                minutes_before=raw_event.get("reminderMinutesBeforeStart", 0),
            ))
        
        recurrence = None
        if raw_event.get("recurrence"):
            recurrence = self._parse_outlook_recurrence(raw_event["recurrence"])
        
        location = None
        if raw_event.get("location"):
            location = raw_event["location"].get("displayName")
        
        return Event(
            id=raw_event.get("id", ""),
            calendar_id=raw_event.get("calendar_id", ""),
            title=raw_event.get("subject", ""),
            description=raw_event.get("bodyPreview"),
            location=location,
            start=start_dt,
            end=end_dt,
            timezone=timezone,
            attendees=attendees,
            reminders=reminders,
            recurrence=recurrence,
            status=raw_event.get("showAs", "free"),
            created_at=self._parse_datetime(raw_event.get("createdDateTime")),
            updated_at=self._parse_datetime(raw_event.get("lastModifiedDateTime")),
            etag=raw_event.get("changeKey"),
            is_recurring_master=bool(raw_event.get("recurrence")),
            recurrence_id=raw_event.get("seriesMasterId"),
            provider_metadata={"webLink": raw_event.get("webLink")},
        )
    
    def _denormalize_google_event(self, event: Event) -> dict[str, Any]:
        """Denormalize to Google Calendar format.
        
        Args:
            event: Unified Event object.
            
        Returns:
            Google Calendar API event dictionary.
        """
        body = {
            "summary": event.title,
            "start": {
                "dateTime": event.start.isoformat() if isinstance(event.start, datetime) else event.start,
                "timeZone": event.timezone,
            },
            "end": {
                "dateTime": event.end.isoformat() if isinstance(event.end, datetime) else event.end,
                "timeZone": event.timezone,
            },
        }
        
        if event.description:
            body["description"] = event.description
        if event.location:
            body["location"] = event.location
        if event.attendees:
            body["attendees"] = [
                {"email": a.email, "displayName": a.name}
                for a in event.attendees
            ]
        if event.reminders:
            body["reminders"] = {
                "useDefault": False,
                "overrides": [
                    {"method": r.method, "minutes": r.minutes_before}
                    for r in event.reminders
                ],
            }
        if event.recurrence:
            body["recurrence"] = self._build_google_recurrence(event.recurrence)
        
        return body
    
    def _denormalize_outlook_event(self, event: Event) -> dict[str, Any]:
        """Denormalize to Outlook Calendar format.
        
        Args:
            event: Unified Event object.
            
        Returns:
            Microsoft Graph API event dictionary.
        """
        body = {
            "subject": event.title,
            "start": {
                "dateTime": event.start.isoformat() if isinstance(event.start, datetime) else event.start,
                "timeZone": event.timezone,
            },
            "end": {
                "dateTime": event.end.isoformat() if isinstance(event.end, datetime) else event.end,
                "timeZone": event.timezone,
            },
        }
        
        if event.description:
            body["body"] = {
                "contentType": "HTML",
                "content": event.description,
            }
        if event.location:
            body["location"] = {"displayName": event.location}
        if event.attendees:
            body["attendees"] = [
                {
                    "emailAddress": {"address": a.email, "name": a.name or ""},
                    "type": "required",
                }
                for a in event.attendees
            ]
        if event.reminders:
            body["isReminderOn"] = True
            body["reminderMinutesBeforeStart"] = event.reminders[0].minutes_before
        if event.recurrence:
            body["recurrence"] = self._build_outlook_recurrence(event.recurrence)
        
        return body
    
    def _parse_datetime(self, dt_str: Optional[str]) -> Optional[datetime]:
        """Parse a datetime string to datetime object.
        
        Args:
            dt_str: ISO 8601 datetime string.
            
        Returns:
            Parsed datetime object or None.
        """
        if not dt_str:
            return None
        
        try:
            if "T" in dt_str:
                return datetime.fromisoformat(dt_str)
            else:
                return datetime.strptime(dt_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            logger.warning(f"Failed to parse datetime: {dt_str}")
            return None
    
    def _parse_recurrence_rules(self, rules: list[str]) -> Optional[RecurrenceRule]:
        """Parse Google recurrence rules.
        
        Args:
            rules: List of RRULE strings.
            
        Returns:
            RecurrenceRule object or None.
        """
        if not rules:
            return None
        
        rule_str = rules[0].replace("RRULE:", "")
        parts = dict(part.split("=", 1) for part in rule_str.split(";") if "=" in part)
        
        frequency_map = {
            "DAILY": "daily",
            "WEEKLY": "weekly",
            "MONTHLY": "monthly",
            "YEARLY": "yearly",
        }
        
        return RecurrenceRule(
            frequency=frequency_map.get(parts.get("FREQ", "weekly"), "weekly"),
            interval=int(parts.get("INTERVAL", 1)),
            count=int(parts["COUNT"]) if "COUNT" in parts else None,
            until=self._parse_datetime(parts.get("UNTIL")),
            by_day=parts.get("BYDAY", "").split(",") if "BYDAY" in parts else None,
            by_month_day=None,
        )
    
    def _parse_outlook_recurrence(self, recurrence: dict) -> Optional[RecurrenceRule]:
        """Parse Outlook recurrence.
        
        Args:
            recurrence: Outlook recurrence dictionary.
            
        Returns:
            RecurrenceRule object or None.
        """
        pattern = recurrence.get("pattern", {})
        
        frequency_map = {
            "daily": "daily",
            "weekly": "weekly",
            "absoluteMonthly": "monthly",
            "relativeMonthly": "monthly",
            "absoluteYearly": "yearly",
            "relativeYearly": "yearly",
        }
        
        return RecurrenceRule(
            frequency=frequency_map.get(pattern.get("type", "weekly"), "weekly"),
            interval=pattern.get("interval", 1),
            count=None,
            until=None,
            by_day=pattern.get("daysOfWeek"),
            by_month_day=None,
        )
    
    def _build_google_recurrence(self, rule: RecurrenceRule) -> list[str]:
        """Build Google recurrence rule string.
        
        Args:
            rule: RecurrenceRule object.
            
        Returns:
            List with single RRULE string.
        """
        frequency_map = {
            "daily": "DAILY",
            "weekly": "WEEKLY",
            "monthly": "MONTHLY",
            "yearly": "YEARLY",
        }
        
        parts = [f"RRULE:FREQ={frequency_map.get(rule.frequency, 'WEEKLY')}"]
        
        if rule.interval and rule.interval != 1:
            parts[0] += f";INTERVAL={rule.interval}"
        if rule.count:
            parts[0] += f";COUNT={rule.count}"
        if rule.until:
            parts[0] += f";UNTIL={rule.until.strftime('%Y%m%dT%H%M%SZ')}"
        if rule.by_day:
            parts[0] += f";BYDAY={','.join(rule.by_day)}"
        
        return parts
    
    def _build_outlook_recurrence(self, rule: RecurrenceRule) -> dict:
        """Build Outlook recurrence structure.
        
        Args:
            rule: RecurrenceRule object.
            
        Returns:
            Outlook recurrence dictionary.
        """
        pattern_type_map = {
            "daily": "daily",
            "weekly": "weekly",
            "monthly": "absoluteMonthly",
            "yearly": "absoluteYearly",
        }
        
        return {
            "pattern": {
                "type": pattern_type_map.get(rule.frequency, "weekly"),
                "interval": rule.interval or 1,
                "daysOfWeek": rule.by_day or [],
            },
            "range": {
                "type": "noEnd",
                "startDate": rule.until.strftime("%Y-%m-%d") if rule.until else None,
            },
        }
