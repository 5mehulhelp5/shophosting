"""
ShopHosting.io - Slow Query Viewer Module

Provides paginated access to slow queries for premium customers.
Queries are sanitized to prevent exposure of literal values.

Table: slow_queries
- id: Primary key
- customer_id: Foreign key to customers
- query_hash: MD5 hash for deduplication
- query_text: Full query text
- execution_time_ms: Average execution time
- rows_examined: Rows examined
- rows_sent: Rows returned
- first_seen: When query was first detected
- last_seen: When query was last seen
- occurrence_count: How many times query was executed
"""

import logging
import re
import math
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Query Sanitization
# =============================================================================

def sanitize_query_text(query: str, max_length: int = 500) -> str:
    """
    Sanitize query text for display to prevent exposure of sensitive data.

    - Replaces string literals with placeholder
    - Replaces numeric literals with placeholder
    - Truncates to max_length

    Args:
        query: The raw SQL query text
        max_length: Maximum length for truncated preview

    Returns:
        Sanitized query text
    """
    if not query:
        return ''

    # Replace string literals (both single and double quoted)
    # Handles escaped quotes within strings
    sanitized = re.sub(r"'(?:[^'\\]|\\.)*'", "'?'", query)
    sanitized = re.sub(r'"(?:[^"\\]|\\.)*"', '"?"', sanitized)

    # Replace numeric literals (integers and decimals)
    # But not in table names or aliases (preceded by letters or underscore)
    sanitized = re.sub(r'(?<![a-zA-Z_])\b\d+\.?\d*\b', '?', sanitized)

    # Replace IN lists with placeholder
    sanitized = re.sub(r'IN\s*\(\s*[\?,\s]+\)', 'IN (?)', sanitized, flags=re.IGNORECASE)

    # Normalize whitespace
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()

    return sanitized


def truncate_query(query: str, max_length: int = 100) -> str:
    """
    Truncate query for preview display.

    Args:
        query: The query text
        max_length: Maximum preview length

    Returns:
        Truncated query with ellipsis if needed
    """
    if not query:
        return ''

    if len(query) <= max_length:
        return query

    return query[:max_length - 3] + '...'


# =============================================================================
# Time Range Helpers
# =============================================================================

def get_time_range_filter(time_range: str) -> timedelta:
    """
    Convert time range string to timedelta.

    Args:
        time_range: '24h', '7d', or '30d'

    Returns:
        timedelta for the specified range
    """
    ranges = {
        '24h': timedelta(hours=24),
        '7d': timedelta(days=7),
        '30d': timedelta(days=30),
    }
    return ranges.get(time_range, timedelta(days=7))


# =============================================================================
# Slow Query Retrieval
# =============================================================================

class SlowQueryViewer:
    """
    Retrieves and formats slow queries for the customer dashboard.
    """

    def __init__(self, db_connection_func=None):
        """
        Initialize the viewer.

        Args:
            db_connection_func: Function that returns a database connection.
                              If None, will import from models.
        """
        self._get_db_connection = db_connection_func

    def _get_connection(self):
        """Get database connection"""
        if self._get_db_connection:
            return self._get_db_connection()
        from models import get_db_connection
        return get_db_connection(read_only=True)

    def get_slow_queries(
        self,
        customer_id: int,
        page: int = 1,
        limit: int = 20,
        sort_by: str = 'time',
        time_range: str = '7d'
    ) -> Dict[str, Any]:
        """
        Get paginated slow queries for a customer.

        Args:
            customer_id: The customer ID
            page: Page number (1-indexed)
            limit: Number of items per page
            sort_by: 'time' for execution time, 'count' for occurrence count
            time_range: '24h', '7d', or '30d'

        Returns:
            Dictionary with queries, pagination, and filter info:
            {
                'queries': [...],
                'pagination': {...},
                'filters': {...}
            }
        """
        conn = self._get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            # Calculate time filter
            time_delta = get_time_range_filter(time_range)
            cutoff_time = datetime.now() - time_delta

            # Determine sort column
            if sort_by == 'count':
                order_by = 'occurrence_count DESC'
            else:  # 'time' is default
                order_by = 'execution_time_ms DESC'

            # Get total count
            cursor.execute("""
                SELECT COUNT(*) as total
                FROM slow_queries
                WHERE customer_id = %s
                  AND last_seen >= %s
            """, (customer_id, cutoff_time))
            total = cursor.fetchone()['total']

            # Calculate pagination
            offset = (page - 1) * limit
            total_pages = math.ceil(total / limit) if total > 0 else 1

            # Get queries with pagination
            cursor.execute(f"""
                SELECT
                    id,
                    query_hash,
                    query_text,
                    execution_time_ms,
                    rows_examined,
                    rows_sent,
                    first_seen,
                    last_seen,
                    occurrence_count
                FROM slow_queries
                WHERE customer_id = %s
                  AND last_seen >= %s
                ORDER BY {order_by}
                LIMIT %s OFFSET %s
            """, (customer_id, cutoff_time, limit, offset))

            rows = cursor.fetchall()

            # Format queries for response
            queries = []
            for row in rows:
                # Sanitize and truncate query text
                sanitized_query = sanitize_query_text(row['query_text'])
                query_preview = truncate_query(sanitized_query, max_length=100)

                queries.append({
                    'id': row['id'],
                    'query_hash': row['query_hash'],
                    'query_text': sanitized_query,
                    'query_preview': query_preview,
                    'avg_execution_time_ms': row['execution_time_ms'],
                    'rows_examined': row['rows_examined'],
                    'rows_sent': row['rows_sent'],
                    'occurrence_count': row['occurrence_count'],
                    'first_seen': row['first_seen'].isoformat() if row['first_seen'] else None,
                    'last_seen': row['last_seen'].isoformat() if row['last_seen'] else None,
                })

            return {
                'queries': queries,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'total_pages': total_pages,
                },
                'filters': {
                    'sort': sort_by,
                    'range': time_range,
                }
            }

        except Exception as e:
            logger.error(f"Error fetching slow queries for customer {customer_id}: {e}")
            raise
        finally:
            cursor.close()
            conn.close()


# =============================================================================
# Public API Function
# =============================================================================

def get_slow_queries(
    customer_id: int,
    page: int = 1,
    limit: int = 20,
    sort_by: str = 'time',
    time_range: str = '7d'
) -> Dict[str, Any]:
    """
    Get slow queries for a customer (premium feature).

    This is the main public API function that creates a viewer
    instance and returns slow queries as a dictionary.

    Args:
        customer_id: The customer ID to get slow queries for
        page: Page number (1-indexed, default 1)
        limit: Number of items per page (default 20)
        sort_by: Sort field - 'time' or 'count' (default 'time')
        time_range: Time range - '24h', '7d', '30d' (default '7d')

    Returns:
        Dictionary with queries, pagination info, and applied filters:
        {
            'queries': [
                {
                    'id': 123,
                    'query_hash': 'abc123...',
                    'query_text': 'SELECT ... FROM ... WHERE ...',
                    'query_preview': 'SELECT ... FROM ...',
                    'avg_execution_time_ms': 2500,
                    'rows_examined': 10000,
                    'rows_sent': 100,
                    'occurrence_count': 15,
                    'first_seen': '2026-02-01T10:00:00',
                    'last_seen': '2026-02-01T14:30:00'
                },
                ...
            ],
            'pagination': {
                'page': 1,
                'limit': 20,
                'total': 45,
                'total_pages': 3
            },
            'filters': {
                'sort': 'time',
                'range': '7d'
            }
        }
    """
    viewer = SlowQueryViewer()
    return viewer.get_slow_queries(
        customer_id=customer_id,
        page=page,
        limit=limit,
        sort_by=sort_by,
        time_range=time_range
    )
