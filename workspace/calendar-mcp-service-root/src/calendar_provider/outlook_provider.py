"""Outlook Calendar provider implementation.

Concrete implementation of CalendarProvider using the Microsoft Graph API
via the msgraph-sdk library.
"""

import logging
from typing import Optional
from datetime import datetime

from src.calendar_provider.base import CalendarProvider
from src.models.calendar import Calendar, Event, FreeBusySlot, EventAttendee, EventReminder, RecurrenceRule
from src.auth.oauth_manager import OAuthManager
from src.services.error_handler import ErrorHandler

logger = logging.getLogger(__name__)


class OutlookCalendarProvider(CalendarProvider):
    """Microsoft Graph Calendar API provider implementation.
    
    Implements the CalendarProvider interface using Microsoft Graph API.
    Handles OAuth2 authentication and Outlook-specific event formats.
    """
    
    PROVIDER_NAME = "outlook"
    
    def __init__(self, oauth_manager: OAuthManager, error_handler: ErrorHandler) -> None:
        """Initialize Outlook Calendar provider.
        
        Args:
            oauth_manager: OAuth2 token manager for authentication.
            error_handler: Error handler for provider errors.
        """
        self._oauth_manager = oauth_manager
        self._error_handler = error_handler
        self._client = None
    
    async def _get_client(self):
        """Get or create the Microsoft Graph client.
        
        Returns:
            Microsoft Graph client instance.
        """
        if self._client is None:
            from kiota_authentication_azure.azure_authentication import AzureIdentityAuthenticationProvider
            from msgraph import GraphServiceClient
            from azure.identity import AccessTokenCredential
            
            access_token = await self._oauth_manager.get_credentials(self.PROVIDER_NAME)
            
            # Create a credential object from the access token
            credential = AccessTokenCredential(access_token)
            auth_provider = AzureIdentityAuthenticationProvider(credential)
            self._client = GraphServiceClient(auth_provider)
        
        return self._client
    
    async def list_calendars(self) -> list[Calendar]:
        """List all accessible Outlook calendars.
        
        Returns:
            List of Calendar objects.
        """
        try:
            client = await self._get_client()
            calendars_result = await client.me.calendars.get()
            
            calendars = []
            if calendars_result and calendars_result.value:
                for item in calendars_result.value:
                    calendar = Calendar(
                        id=item.id,
                        name=item.name or "",
                        description=item.change_key,
                        timezone="UTC",  # Outlook uses Windows timezone names
                        is_primary=getattr(item, 'is_default_calendar', False),
                        access_role="owner",
                        color=item.hex_color if hasattr(item, 'hex_color') else None,
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
        """Retrieve events from Outlook Calendar.
        
        Args:
            calendar_id: Calendar ID or None for default.
            start_time: Start of date range (ISO 8601).
            end_time: End of date range (ISO 8601).
            max_results: Maximum events to return.
            expand_recurring: Whether to expand recurring events.
            
        Returns:
            List of Event objects.
        """
        try:
            client = await self._get_client()
            
            # Build query parameters
            query_params = {
                "$top": max_results,
                "$orderby": "start/dateTime",
            }
            
            if start_time and end_time:
                filter_str = f"start/dateTime ge '{start_time}' and start/dateTime le '{end_time}'"
                query_params["$filter"] = filter_str
            
            if calendar_id:
                events_result = await client.me.calendars.by_calendar_id(calendar_id).events.get(
                    q=query_params,
                )
            else:
                events_result = await client.me.events.get(q=query_params)
            
            events = []
            if events_result and events_result.value:
                for item in events_result.value:
                    event = self._parse_outlook_event(item, calendar_id)
                    events.append(event)
            
            return events
            
        except Exception as e:
            raise self._error_handler.handle_provider_error(e, self.PROVIDER_NAME)
    
    async def create_event(self, event: Event) -> Event:
        """Create a new event in Outlook Calendar.
        
        Args:
            event: Event object to create.
            
        Returns:
            Created Event with provider-assigned ID.
        """
        try:
            client = await self._get_client()
            
            body = self._build_outlook_event(event)
            
            if event.calendar_id:
                created = await client.me.calendars.by_calendar_id(event.calendar_id).events.post(body)
            else:
                created = await client.me.events.post(body)
            
            return self._parse_outlook_event(created, event.calendar_id)
            
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
        """Update an existing Outlook Calendar event.
        
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
            client = await self._get_client()
            
            if calendar_id:
                updated = await client.me.calendars.by_calendar_id(calendar_id).events.by_event_id(event_id).patch(
                    body=updates,
                )
            else:
                updated = await client.me.events.by_event_id(event_id).patch(body=updates)
            
            return self._parse_outlook_event(updated, calendar_id)
            
        except Exception as e:
            raise self._error_handler.handle_provider_error(e, self.PROVIDER_NAME)
    
    async def delete_event(
        self,
        event_id: str,
        calendar_id: Optional[str] = None,
        send_notifications: bool = True,
        delete_series: bool = False,
    ) -> bool:
        """Delete an Outlook Calendar event.
        
        Args:
            event_id: Event ID to delete.
            calendar_id: Calendar containing the event.
            send_notifications: Whether to send cancellation notices.
            delete_series: Whether to delete entire series.
            
        Returns:
            True if successful.
        """
        try:
            client = await self._get_client()
            
            if calendar_id:
                await client.me.calendars.by_calendar_id(calendar_id).events.by_event_id(event_id).delete()
            else:
                await client.me.events.by_event_id(event_id).delete()
            
            return True
            
        except Exception as e:
            raise self._error_handler.handle_provider_error(e, self.PROVIDER_NAME)
    
    async def get_free_busy(
        self,
        start_time: str,
        end_time: str,
        calendar_ids: Optional[list[str]] = None,
    ) -> list[FreeBusySlot]:
        """Get free/busy information from Outlook Calendar.
        
        Args:
            start_time: Start of time range (ISO 8601).
            end_time: End of time range (ISO 8601).
            calendar_ids: Calendars to check (all if None).
            
        Returns:
            List of FreeBusySlot objects.
        """
        try:
            client = await self._get_client()
            
            # Get events in the time range to determine busy slots
            events = await self.get_events(
                start_time=start_time,
                end_time=end_time,
            )
            
            slots = []
            for event in events:
                status = "busy" if event.status == "confirmed" else event.status
                slot = FreeBusySlot(
                    start=event.start,
                    end=event.end,
                    status=status,
                )
                slots.append(slot)
            
            return slots
            
        except Exception as e:
            raise self._error_handler.handle_provider_error(e, self.PROVIDER_NAME)
    
    def _parse_outlook_event(self, outlook_event, calendar_id: str) -> Event:
        """Parse an Outlook Graph API event to unified Event model.
        
        Args:
            outlook_event: Raw event from Microsoft Graph API.
            calendar_id: Calendar ID the event belongs to.
            
        Returns:
            Unified Event object.
        """
        start_info = getattr(outlook_event, 'start', None)
        end_info = getattr(outlook_event, 'end', None)
        
        start_dt = None
        end_dt = None
        timezone = "UTC"
        
        if start_info:
            start_dt = getattr(start_info, 'date_time', None) or getattr(start_info, 'dateTime', None)
            timezone = getattr(start_info, 'time_zone', None) or getattr(start_info, 'timezone', 'UTC')
        
        if end_info:
            end_dt = getattr(end_info, 'date_time', None) or getattr(end_info, 'dateTime', None)
        
        attendees = []
        outlook_attendees = getattr(outlook_event, 'attendees', []) or []
        for att in outlook_attendees:
            email_addr = getattr(att, 'email_address', None)
            if email_addr:
                attendee = EventAttendee(
                    email=getattr(email_addr, 'address', ''),
                    name=getattr(email_addr, 'name', None),
                    response_status=getattr(att, 'status', {}).get('response') if hasattr(att, 'status') else None,
                    is_organizer=False,
                )
                attendees.append(attendee)
        
        reminders = []
        outlook_reminders = getattr(outlook_event, 'reminder_minutes_before_start', None)
        if outlook_reminders is not None:
            reminder = EventReminder(
                method="popup",
                minutes_before=outlook_reminders,
            )
            reminders.append(reminder)
        
        recurrence = None
        outlook_recurrence = getattr(outlook_event, 'recurrence', None)
        if outlook_recurrence:
            recurrence = self._parse_outlook_recurrence(outlook_recurrence)
        
        return Event(
            id=getattr(outlook_event, 'id', ''),
            calendar_id=calendar_id or "",
            title=getattr(outlook_event, 'subject', ''),
            description=getattr(outlook_event, 'body_preview', None),
            location=self._parse_outlook_location(outlook_event),
            start=start_dt,
            end=end_dt,
            timezone=timezone,
            attendees=attendees,
            reminders=reminders,
            recurrence=recurrence,
            status=getattr(outlook_event, 'show_as', 'free'),
            created_at=getattr(outlook_event, 'created_date_time', None),
            updated_at=getattr(outlook_event, 'last_modified_date_time', None),
            etag=getattr(outlook_event, 'change_key', None),
            is_recurring_master=bool(outlook_recurrence),
            recurrence_id=getattr(outlook_event, 'series_master_id', None),
            provider_metadata={"web_link": getattr(outlook_event, 'web_link', None)},
        )
    
    def _build_outlook_event(self, event: Event) -> dict:
        """Build an Outlook Graph API event body from unified Event.
        
        Args:
            event: Unified Event object.
            
        Returns:
            Dictionary suitable for Microsoft Graph API.
        """
        body = {
            "subject": event.title,
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
            body["body"] = {
                "contentType": "HTML",
                "content": event.description,
            }
        
        if event.location:
            body["location"] = {
                "displayName": event.location,
            }
        
        if event.attendees:
            body["attendees"] = [
                {
                    "emailAddress": {
                        "address": a.email,
                        "name": a.name or "",
                    },
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
    
    def _parse_outlook_location(self, outlook_event) -> Optional[str]:
        """Extract location string from Outlook event.
        
        Args:
            outlook_event: Raw Outlook event object.
            
        Returns:
            Location string or None.
        """
        location = getattr(outlook_event, 'location', None)
        if location:
            return getattr(location, 'display_name', None) or getattr(location, 'displayName', None)
        return None
    
    def _parse_outlook_recurrence(self, recurrence) -> Optional[RecurrenceRule]:
        """Parse Outlook recurrence to unified RecurrenceRule.
        
        Args:
            recurrence: Outlook recurrence object.
            
        Returns:
            RecurrenceRule object or None.
        """
        if not recurrence:
            return None
        
        pattern = getattr(recurrence, 'pattern', None)
        if not pattern:
            return None
        
        frequency_map = {
            "daily": "daily",
            "weekly": "weekly",
            "absoluteMonthly": "monthly",
            "relativeMonthly": "monthly",
            "absoluteYearly": "yearly",
            "relativeYearly": "yearly",
        }
        
        freq_type = getattr(pattern, 'type', 'weekly').lower()
        
        return RecurrenceRule(
            frequency=frequency_map.get(freq_type, "weekly"),
            interval=getattr(pattern, 'interval', 1),
            count=None,
            until=None,
            by_day=getattr(pattern, 'days_of_week', None),
            by_month_day=None,
        )
    
    def _build_outlook_recurrence(self, rule: RecurrenceRule) -> dict:
        """Build Outlook recurrence from unified RecurrenceRule.
        
        Args:
            rule: Unified RecurrenceRule object.
            
        Returns:
            Dictionary suitable for Microsoft Graph API.
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
