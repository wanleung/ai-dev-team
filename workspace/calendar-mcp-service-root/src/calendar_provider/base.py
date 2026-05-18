"""Abstract base class for calendar providers.

Defines the unified interface that all calendar provider implementations
must follow, abstracting provider-specific differences.
"""

from abc import ABC, abstractmethod
from typing import Optional

from src.models.calendar import Calendar, Event, FreeBusySlot


class CalendarProvider(ABC):
    """Abstract base class for calendar provider implementations.
    
    All calendar providers (Google, Outlook, etc.) must implement
    this interface to ensure consistent behavior across providers.
    """
    
    @abstractmethod
    async def list_calendars(self) -> list[Calendar]:
        """List all accessible calendars for the authenticated user.
        
        Returns:
            List of Calendar objects the user has access to.
            
        Raises:
            AuthenticationError: If credentials are invalid or expired.
            ProviderError: If the provider API request fails.
        """
        pass
    
    @abstractmethod
    async def get_events(
        self,
        calendar_id: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        max_results: int = 100,
        expand_recurring: bool = True,
    ) -> list[Event]:
        """Retrieve events for a specified date range.
        
        Args:
            calendar_id: Optional calendar ID (uses primary if None).
            start_time: Start of date range (ISO 8601).
            end_time: End of date range (ISO 8601).
            max_results: Maximum number of events to return.
            expand_recurring: Whether to expand recurring events.
            
        Returns:
            List of Event objects within the specified range.
            
        Raises:
            AuthenticationError: If credentials are invalid or expired.
            ProviderError: If the provider API request fails.
        """
        pass
    
    @abstractmethod
    async def create_event(self, event: Event) -> Event:
        """Create a new calendar event.
        
        Args:
            event: Event object with details to create.
            
        Returns:
            Created Event object with provider-assigned ID.
            
        Raises:
            AuthenticationError: If credentials are invalid or expired.
            ProviderError: If the provider API request fails.
        """
        pass
    
    @abstractmethod
    async def update_event(
        self,
        event_id: str,
        updates: dict,
        calendar_id: Optional[str] = None,
        send_notifications: bool = True,
        update_series: bool = False,
    ) -> Event:
        """Update an existing calendar event.
        
        Args:
            event_id: ID of the event to update.
            updates: Dictionary of fields to update.
            calendar_id: Calendar containing the event.
            send_notifications: Whether to notify attendees.
            update_series: Whether to update entire recurring series.
            
        Returns:
            Updated Event object.
            
        Raises:
            AuthenticationError: If credentials are invalid or expired.
            ProviderError: If the provider API request fails.
            NotFoundError: If the event doesn't exist.
        """
        pass
    
    @abstractmethod
    async def delete_event(
        self,
        event_id: str,
        calendar_id: Optional[str] = None,
        send_notifications: bool = True,
        delete_series: bool = False,
    ) -> bool:
        """Delete a calendar event.
        
        Args:
            event_id: ID of the event to delete.
            calendar_id: Calendar containing the event.
            send_notifications: Whether to send cancellation notices.
            delete_series: Whether to delete entire recurring series.
            
        Returns:
            True if deletion was successful.
            
        Raises:
            AuthenticationError: If credentials are invalid or expired.
            ProviderError: If the provider API request fails.
            NotFoundError: If the event doesn't exist.
        """
        pass
    
    @abstractmethod
    async def get_free_busy(
        self,
        start_time: str,
        end_time: str,
        calendar_ids: Optional[list[str]] = None,
    ) -> list[FreeBusySlot]:
        """Check availability for a specified time range.
        
        Args:
            start_time: Start of time range (ISO 8601).
            end_time: End of time range (ISO 8601).
            calendar_ids: Optional list of calendars to check.
            
        Returns:
            List of FreeBusySlot objects showing availability.
            
        Raises:
            AuthenticationError: If credentials are invalid or expired.
            ProviderError: If the provider API request fails.
        """
        pass
