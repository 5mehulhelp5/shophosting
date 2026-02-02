"""
Terminal session manager

Handles terminal session state including current working directory tracking.
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Session timeout in minutes
SESSION_TIMEOUT_MINUTES = 30

# Base directory for all terminal operations
BASE_DIRECTORY = '/var/www/html'


class TerminalSession:
    """Represents a terminal session for a customer."""

    def __init__(self, session_id: str, customer_id: int,
                 current_directory: str = BASE_DIRECTORY,
                 created_at: datetime = None,
                 last_activity_at: datetime = None):
        self.id = session_id
        self.customer_id = customer_id
        self.current_directory = current_directory
        self.created_at = created_at or datetime.utcnow()
        self.last_activity_at = last_activity_at or datetime.utcnow()

    @classmethod
    def create(cls, customer_id: int) -> 'TerminalSession':
        """Create a new terminal session."""
        from models import get_db_connection

        session_id = str(uuid.uuid4())
        now = datetime.utcnow()

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO terminal_sessions
                (id, customer_id, current_directory, created_at, last_activity_at)
                VALUES (%s, %s, %s, %s, %s)
            """, (session_id, customer_id, BASE_DIRECTORY, now, now))
            conn.commit()

            logger.info(f"Created terminal session {session_id} for customer {customer_id}")

            return cls(
                session_id=session_id,
                customer_id=customer_id,
                current_directory=BASE_DIRECTORY,
                created_at=now,
                last_activity_at=now
            )
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to create terminal session: {e}")
            raise
        finally:
            cursor.close()
            conn.close()

    @classmethod
    def get(cls, session_id: str) -> Optional['TerminalSession']:
        """Get a terminal session by ID."""
        from models import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("""
                SELECT id, customer_id, current_directory, created_at, last_activity_at
                FROM terminal_sessions
                WHERE id = %s
            """, (session_id,))

            row = cursor.fetchone()
            if not row:
                return None

            # Check if session is expired
            last_activity = row['last_activity_at']
            if isinstance(last_activity, datetime):
                if datetime.utcnow() - last_activity > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
                    logger.info(f"Session {session_id} expired")
                    cls.delete(session_id)
                    return None

            return cls(
                session_id=row['id'],
                customer_id=row['customer_id'],
                current_directory=row['current_directory'],
                created_at=row['created_at'],
                last_activity_at=row['last_activity_at']
            )
        finally:
            cursor.close()
            conn.close()

    def save(self) -> None:
        """Save session state to database."""
        from models import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE terminal_sessions
                SET current_directory = %s, last_activity_at = %s
                WHERE id = %s
            """, (self.current_directory, datetime.utcnow(), self.id))
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to save terminal session {self.id}: {e}")
            raise
        finally:
            cursor.close()
            conn.close()

    def touch(self) -> None:
        """Update last activity timestamp."""
        from models import get_db_connection

        self.last_activity_at = datetime.utcnow()

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                UPDATE terminal_sessions
                SET last_activity_at = %s
                WHERE id = %s
            """, (self.last_activity_at, self.id))
            conn.commit()
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def delete(session_id: str) -> None:
        """Delete a terminal session."""
        from models import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("DELETE FROM terminal_sessions WHERE id = %s", (session_id,))
            conn.commit()
            logger.info(f"Deleted terminal session {session_id}")
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def cleanup_expired() -> int:
        """Clean up expired sessions. Returns count of deleted sessions."""
        from models import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                DELETE FROM terminal_sessions
                WHERE last_activity_at < DATE_SUB(NOW(), INTERVAL %s MINUTE)
            """, (SESSION_TIMEOUT_MINUTES,))
            deleted = cursor.rowcount
            conn.commit()

            if deleted > 0:
                logger.info(f"Cleaned up {deleted} expired terminal sessions")

            return deleted
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def get_active_count(customer_id: int) -> int:
        """Get count of active sessions for a customer."""
        from models import get_db_connection

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                SELECT COUNT(*) FROM terminal_sessions
                WHERE customer_id = %s
                AND last_activity_at > DATE_SUB(NOW(), INTERVAL %s MINUTE)
            """, (customer_id, SESSION_TIMEOUT_MINUTES))
            return cursor.fetchone()[0]
        finally:
            cursor.close()
            conn.close()
