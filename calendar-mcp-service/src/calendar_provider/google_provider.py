"""Google Calendar provider implementation.

Concrete implementation of CalendarProvider using the Google Calendar API v3
via the google-api-python-client library.
"""

import logging
from typing import Optional

from src.calendar_provider.base import CalendarProvider
from src.models.calendar import Calendar, Event, FreeBusySlot, EventAttendee, EventReminder, RecurrenceRule
from src.auth.oauth_manager import OAuthManager
from src.services.error_handler import ErrorHandler

logger = logging.getLogger(__name__)


class GoogleCalendarProvider(CalendarProvider):
    """Google Calendar API v3 provider implementation.
    
    Implements the CalendarProvider interface using Google's Calendar API.
    Handles OAuth2 authentication and Google-specific event formats.
    """
    
    PROVIDER_NAME = "google"
    
    def __init__(self, oauth_manager: OAuthManager, error_handler: ErrorHandler) -> None:
        """Initialize Google Calendar provider.
        
        Args:
            oauth_manager: OAuth2 token manager for authentication.
            error_handler: Error handler for provider errors.
        """
        self._oauth_manager = oauth_manager
        self._error_handler = error_handler
        self._service = None
    
    async def _get_service(self):
        """Get or create the Google Calendar API service.
        
        Returns:
            Google Calendar API service instance.
        """
        if self._service is None:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            
            credentials = await self._oauth_manager.get_credentials(self.PROVIDER_NAME)
            
            self._service = build(
                "calendar",
                "v3",
                credentials=credentials,
            )
        
        return self._service
    
    async def list_calendars(self) -> list[Calendar]:
        """List all accessible Google calendars.
        
        Returns:
            List of Calendar objects.
        """
        try:
            service = await self._get_service()
            calendar_list = service.calendarList().list().execute()
            
            calendars = []
            for item in calendar_list.get("items", []):
                calendar = Calendar(
                    id=item["id"],
                    name=item.get("summary", ""),
                    description=item.get("description"),
                    timezone=item.get("timeZone", "UTC"),
                    is_primary=item.get("primary", False),
                    access_role=item.get("accessRole", "reader"),
                    color=item.get("backgroundColor"),
                )
                calendars.append(calendar)
            
            return calendars
            
        except Exception as e:
            raise self._error_handler.handle_provider_error(e, self.PROVIDER_NAME)
    
    async def get_events(
        self,
        calendar_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        max_results: int = 100,
        expand_recurring: bool = True,
    ) -> list[Event]:
        """Retrieve events from Google Calendar.
        
        Args:
            calendar_id: Calendar ID or 'primary' for default.
            start_time: Start of date range (ISO 8601).
            end_time: End of date range (ISO 8601).
            max_results: Maximum events to return.
            expand_recurring: Whether to expand recurring events.
            
        Returns:
            List of Event objects.
        """
        try:
            service = await self._get_service()
            target_calendar = calendar_id or "primary"
            
            params = {
                "calendarId": target_calendar,
                "maxResults": max_results,
                "singleEvents": expand_recurring,
                "orderBy": "startTime" if expand_recurring else None,
            }
            
            if start_time:
                params["timeMin"] = start_time
            if end_time:
                params["timeMax"] = end_time
            
            # Remove None values
            params = {k: v for k, v in params.items() if v is not None}
            
            events_result = service.events().list(**params).execute()
            events = []
            
            for item in events_result.get("items", []):
                event = self._parse_google_event(item, target_calendar)
                events.append(event)
            
            return events
            
        except Exception as e:
            raise self._error_handler.handle_provider_error(e, self.PROVIDER_NAME)
    
    async def create_event(self, event: Event) -> Event:
        """Create a new event in Google Calendar.
        
        Args:
            event: Event object to create.
            
        Returns:
            Created Event with provider-assigned ID.
        """
        try:
            service = await self._get_service()
            target_calendar = event.calendar_id or "primary"
            
            body = self._build_google_event(event)
            
            created = service.events().insert(
                calendarId=target_calendar,
                body=body,
                sendNotifications=True,
            ).execute()
            
            return self._parse_google_event(created, target_calendar)
            
        except Exception as e:
            raise self._error_handler.handle_provider_error(e, self.PROVIDER_NAME)
    
    async def update_event(
        self,
        event_id: str,
        updates: dict,
        calendar_id: Optional[str] = None,
        send_notifications: bool = True,
        update_series: bool = False,
    ) -> Event:
        """Update an existing Google Calendar event.
        
        Args:
            event_id: Event ID to update.
            updates: Fields to update.
            calendar_id: Calendar containing the event.
            send_notifications: Whether to notify attendees.
            update_series: Whether to update recurring series.
            
        Returns:
            Updated Event object.
        """
        try:
            service = await self._get_service()
            target_calendar = calendar_id or "primary"
            
            # Get existing event
            existing = service.events().get(
                calendarId=target_calendar,
                eventId=event_id,
            ).execute()
            
            # Merge updates
            existing.update(updates)
            
            updated = service.events().update(
                calendarId=target_calendar,
                eventId=event_id,
                body=existing,
                sendNotifications=send_notifications,
            ).execute()
            
            return self._parse_google_event(updated, target_calendar)
            
        except Exception as e:
            raise self._error_handler.handle_provider_error(e, self.PROVIDER_NAME)
    
    async def delete_event(
        self,
        event_id: str,
        calendar_id: Optional[str] = None,
        send_notifications: bool = True,
        delete_series: bool = False,
    ) -> bool:
        """Delete a Google Calendar event.
        
        Args:
            event_id: Event ID to delete.
            calendar_id: Calendar containing the event.
            send_notifications: Whether to send cancellation notices.
            delete_series: Whether to delete entire series.
            
        Returns:
            True if successful.
        """
        try:
            service = await self._get_service()
            target_calendar = calendar_id or "primary"
            
            service.events().delete(
                calendarId=target_calendar,
                eventId=event_id,
                sendNotifications=send_notifications,
            ).execute()
            
            return True
            
        except Exception as e:
            raise self._error_handler.handle_provider_error(e, self.PROVIDER_NAME)
    
    async def get_free_busy(
        self,
        start_time: str,
        end_time: str,
        calendar_ids: Optional[list[str]] = None,
    ) -> list[FreeBusySlot]:
        """Get free/busy information from Google Calendar.
        
        Args:
            start_time: Start of time range (ISO 8601).
            end_time: End of time range (ISO 8601).
            calendar_ids: Calendars to check (all if None).
            
        Returns:
            List of FreeBusySlot objects.
        """
        try:
            service = await self._get_service()
            
            if calendar_ids is None:
                calendars = await self.list_calendars()
                calendar_ids = [c.id for c in calendars]
            
            body = {
                "timeMin": start_time,
                "timeMax": end_time,
                "items": [{"id": cid} for cid in calendar_ids],
            }
            
            result = service.freebusy().query(body=body).execute()
            
            slots = []
            for calendar_id, busy_info in result.get("calendars", {}).items():
                for busy_period in busy_info.get("busy", []):
                    slot = FreeBusySlot(
                        start=busy_period["start"],
                        end=busy_period["end"],
                        status="busy",
                    )
                    slots.append(slot)
            
            return slots
            
        except Exception as e:
            raise self._error_handler.handle_provider_error(e, self.PROVIDER_NAME)
    
    def _parse_google_event(self, google_event: dict, calendar_id: str) -> Event:
        """Parse a Google Calendar API event to unified Event model.
        
        Args:
            google_event: Raw event from Google API.
            calendar_id: Calendar ID the event belongs to.
            
        Returns:
            Unified Event object.
        """
        start_info = google_event.get("start", {})
        end_info = google_event.get("end", {})
        
        start_dt = start_info.get("dateTime") or start_info.get("date")
        end_dt = end_info.get("dateTime") or end_info.get("date")
        timezone = start_info.get("timeZone", "UTC")
        
        attendees = []
        for att in google_event.get("attendees", []):
            attendee = EventAttendee(
                email=att.get("email", ""),
                name=att.get("displayName"),
                response_status=att.get("responseStatus"),
                is_organizer=att.get("organizer", False),
            )
            attendees.append(attendee)
        
        reminders = []
        for rem in google_event.get("reminders", {}).get("overrides", []):
            reminder = EventReminder(
                method=rem.get("method", "popup"),
                minutes_before=rem.get("minutes", 0),
            )
            reminders.append(reminder)
        
        recurrence = None
        if google_event.get("recurrence"):
            recurrence = self._parse_recurrence(google_event["recurrence"])
        
        return Event(
            id=google_event["id"],
            calendar_id=calendar_id,
            title=google_event.get("summary", ""),
            description=google_event.get("description"),
            location=google_event.get("location"),
            start=start_dt,
            end=end_dt,
            timezone=timezone,
            attendees=attendees,
            reminders=reminders,
            recurrence=recurrence,
            status=google_event.get("status", "confirmed"),
            created_at=google_event.get("created"),
            updated_at=google_event.get("updated"),
            etag=google_event.get("etag"),
            is_recurring_master=bool(google_event.get("recurrence")),
            recurrence_id=google_event.get("recurringEventId"),
            provider_metadata={"htmlLink": google_event.get("htmlLink")},
        )
    
    def _build_google_event(self, event: Event) -> dict:
        """Build a Google Calendar API event body from unified Event.
        
        Args:
            event: Unified Event object.
            
        Returns:
            Dictionary suitable for Google Calendar API.
        """
        body = {
            "summary": event.title,
            "start": {
                "dateTime": event.start,
                "timeZone": event.timezone,
            },
            "end": {
                "dateTime": event.end,
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
            body["recurrence"] = self._build_recurrence(event.recurrence)
        
        return body
    
    def _parse_recurrence(self, recurrence_rules: list[str]) -> Optional[RecurrenceRule]:
        """Parse Google recurrence rules to unified RecurrenceRule.
        
        Args:
            recurrence_rules: List of RRULE strings from Google API.
            
        Returns:
            RecurrenceRule object or None.
        """
        if not recurrence_rules:
            return None
        
        rule_str = recurrence_rules[0]  # First RRULE
        parts = rule_str.replace("RRULE:", "").split(";")
        
        rule_dict = {}
        for part in parts:
            if "=" in part:
                key, value = part.split("=", 1)
                rule_dict[key] = value
        
        frequency_map = {
            "DAILY": "daily",
            "WEEKLY": "weekly",
            "MONTHLY": "monthly",
            "YEARLY": "yearly",
        }
        
        return RecurrenceRule(
            frequency=frequency_map.get(rule_dict.get("FREQ", "weekly"), "weekly"),
            interval=int(rule_dict.get("INTERVAL", 1)),
            count=int(rule_dict["COUNT"]) if "COUNT" in rule_dict else None,
            until=None,  # Parse UNTIL if needed
            by_day=rule_dict.get("BYDAY", "").split(",") if "BYDAY" in rule_dict else None,
            by_month_day=None,
        )
    
    def _build_recurrence(self, rule: RecurrenceRule) -> list[str]:
        """Build Google recurrence rules from unified RecurrenceRule.
        
        Args:
            rule: Unified RecurrenceRule object.
            
        Returns:
            List of RRULE strings for Google API.
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
        if rule.by_day:
            parts[0] += f";BYDAY={','.join(rule.by_day)}"
        
        return parts
