"""
ShopHosting.io - Table Analyzer Module

Provides database table analysis for premium plan customers:
- List all tables with size, row count, and fragmentation %
- Identify tables needing optimization (>20% fragmentation)
- Execute OPTIMIZE TABLE commands on customer databases

Uses docker exec to query customer MySQL containers.
"""

import subprocess
import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)

# Fragmentation threshold for flagging tables
FRAGMENTATION_THRESHOLD = 20.0  # Tables with >20% fragmentation are flagged

# Command timeout for MySQL queries
MYSQL_TIMEOUT = 30  # seconds


@dataclass
class TableStats:
    """Statistics for a single database table"""
    name: str
    rows: int
    data_length: int  # bytes
    index_length: int  # bytes
    data_free: int  # bytes (wasted space)

    @property
    def size_bytes(self) -> int:
        """Total size of the table in bytes"""
        return self.data_length + self.index_length

    @property
    def size_mb(self) -> float:
        """Total size of the table in megabytes"""
        return round(self.size_bytes / (1024 * 1024), 2)

    @property
    def fragmentation_percent(self) -> float:
        """
        Calculate fragmentation percentage.
        Fragmentation = data_free / (data_length + index_length) * 100
        """
        total_size = self.data_length + self.index_length
        if total_size == 0:
            return 0.0
        return round((self.data_free / total_size) * 100, 2)

    @property
    def needs_optimization(self) -> bool:
        """Check if table needs optimization (>20% fragmentation)"""
        return self.fragmentation_percent > FRAGMENTATION_THRESHOLD

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response"""
        return {
            'name': self.name,
            'rows': self.rows,
            'size_bytes': self.size_bytes,
            'size_mb': self.size_mb,
            'data_length': self.data_length,
            'index_length': self.index_length,
            'data_free': self.data_free,
            'fragmentation_percent': self.fragmentation_percent,
            'needs_optimization': self.needs_optimization
        }


def get_db_container_name(customer_id: int) -> str:
    """Get the database container name for a customer"""
    return f"customer-{customer_id}-db"


def check_container_exists(container_name: str) -> bool:
    """Check if a container exists and is running"""
    try:
        result = subprocess.run(
            ['docker', 'inspect', '-f', '{{.State.Running}}', container_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0 and result.stdout.strip() == 'true'
    except Exception:
        return False


def execute_mysql_query(customer_id: int, query: str, database: str = None) -> tuple[bool, str]:
    """
    Execute a MySQL query in the customer's database container.

    Args:
        customer_id: The customer ID
        query: The SQL query to execute
        database: Optional database name to use

    Returns:
        Tuple of (success, output/error_message)
    """
    container_name = get_db_container_name(customer_id)

    if not check_container_exists(container_name):
        return False, f"Database container {container_name} is not running"

    # Build the mysql command
    # We use -N (skip column names) and -B (batch mode) for cleaner output
    mysql_cmd = ['mysql', '-N', '-B', '-e', query]
    if database:
        mysql_cmd.extend(['-D', database])

    # Execute via docker exec
    docker_cmd = [
        'docker', 'exec',
        container_name
    ] + mysql_cmd

    try:
        result = subprocess.run(
            docker_cmd,
            capture_output=True,
            text=True,
            timeout=MYSQL_TIMEOUT
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else 'Unknown error'
            logger.error(f"MySQL query failed for customer {customer_id}: {error_msg}")
            return False, error_msg

        return True, result.stdout

    except subprocess.TimeoutExpired:
        logger.error(f"MySQL query timed out for customer {customer_id}")
        return False, f"Query timed out after {MYSQL_TIMEOUT} seconds"
    except Exception as e:
        logger.error(f"Error executing MySQL query for customer {customer_id}: {e}")
        return False, str(e)


def get_customer_database_name(customer_id: int) -> Optional[str]:
    """
    Get the main database name for a customer.
    Usually it's 'wordpress' for WooCommerce or 'magento' for Magento stores.
    """
    # Query to list non-system databases
    query = """
        SELECT SCHEMA_NAME
        FROM information_schema.SCHEMATA
        WHERE SCHEMA_NAME NOT IN ('mysql', 'information_schema', 'performance_schema', 'sys')
        LIMIT 1;
    """

    success, output = execute_mysql_query(customer_id, query)
    if not success:
        return None

    db_name = output.strip()
    return db_name if db_name else None


def get_table_stats(customer_id: int, database: str = None) -> tuple[bool, List[TableStats] | str]:
    """
    Get statistics for all tables in the customer's database.

    Args:
        customer_id: The customer ID
        database: Optional database name. If not provided, auto-detects.

    Returns:
        Tuple of (success, list_of_TableStats or error_message)
    """
    # Auto-detect database if not provided
    if not database:
        database = get_customer_database_name(customer_id)
        if not database:
            return False, "Could not determine database name"

    # Query table statistics using information_schema
    query = f"""
        SELECT
            TABLE_NAME,
            COALESCE(TABLE_ROWS, 0) as ROWS,
            COALESCE(DATA_LENGTH, 0) as DATA_LENGTH,
            COALESCE(INDEX_LENGTH, 0) as INDEX_LENGTH,
            COALESCE(DATA_FREE, 0) as DATA_FREE
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = '{database}'
          AND TABLE_TYPE = 'BASE TABLE'
        ORDER BY (DATA_LENGTH + INDEX_LENGTH) DESC;
    """

    success, output = execute_mysql_query(customer_id, query)
    if not success:
        return False, output

    tables = []
    for line in output.strip().split('\n'):
        if not line:
            continue

        parts = line.split('\t')
        if len(parts) < 5:
            continue

        try:
            table = TableStats(
                name=parts[0],
                rows=int(parts[1]),
                data_length=int(parts[2]),
                index_length=int(parts[3]),
                data_free=int(parts[4])
            )
            tables.append(table)
        except (ValueError, IndexError) as e:
            logger.warning(f"Failed to parse table stats line: {line}, error: {e}")
            continue

    return True, tables


def get_fragmented_tables(customer_id: int, database: str = None) -> tuple[bool, List[TableStats] | str]:
    """
    Get only tables that need optimization (>20% fragmentation).

    Args:
        customer_id: The customer ID
        database: Optional database name

    Returns:
        Tuple of (success, list_of_TableStats or error_message)
    """
    success, result = get_table_stats(customer_id, database)
    if not success:
        return False, result

    fragmented = [t for t in result if t.needs_optimization]
    return True, fragmented


def optimize_table(customer_id: int, table_name: str, database: str = None) -> tuple[bool, str]:
    """
    Run OPTIMIZE TABLE on a specific table.

    Args:
        customer_id: The customer ID
        table_name: The table to optimize
        database: Optional database name

    Returns:
        Tuple of (success, result_message)
    """
    # Validate table name to prevent SQL injection
    # Table names should only contain alphanumeric, underscore, and dollar sign
    if not re.match(r'^[a-zA-Z_$][a-zA-Z0-9_$]*$', table_name):
        return False, "Invalid table name"

    # Auto-detect database if not provided
    if not database:
        database = get_customer_database_name(customer_id)
        if not database:
            return False, "Could not determine database name"

    # First verify the table exists and is in the expected database
    verify_query = f"""
        SELECT COUNT(*)
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = '{database}'
          AND TABLE_NAME = '{table_name}'
          AND TABLE_TYPE = 'BASE TABLE';
    """

    success, output = execute_mysql_query(customer_id, verify_query)
    if not success:
        return False, f"Failed to verify table: {output}"

    if output.strip() != '1':
        return False, f"Table '{table_name}' not found in database '{database}'"

    # Run OPTIMIZE TABLE
    optimize_query = f"OPTIMIZE TABLE `{database}`.`{table_name}`;"

    logger.info(f"Running OPTIMIZE TABLE for customer {customer_id}, table {database}.{table_name}")

    success, output = execute_mysql_query(customer_id, optimize_query)
    if not success:
        return False, f"Optimization failed: {output}"

    logger.info(f"OPTIMIZE TABLE completed for customer {customer_id}, table {table_name}")

    return True, f"Table '{table_name}' optimization completed successfully"


def get_optimization_suggestions(tables: List[TableStats]) -> List[Dict[str, Any]]:
    """
    Generate optimization suggestions based on table statistics.

    Args:
        tables: List of TableStats objects

    Returns:
        List of suggestion dictionaries
    """
    suggestions = []

    # Check for fragmented tables
    fragmented = [t for t in tables if t.needs_optimization]
    if fragmented:
        total_wasted = sum(t.data_free for t in fragmented)
        wasted_mb = round(total_wasted / (1024 * 1024), 2)

        suggestions.append({
            'type': 'fragmentation',
            'severity': 'warning' if len(fragmented) < 5 else 'high',
            'title': f'{len(fragmented)} table(s) need optimization',
            'message': f'Optimize fragmented tables to reclaim approximately {wasted_mb} MB of disk space.',
            'tables': [t.name for t in fragmented[:5]],  # Limit to 5 for display
            'action': 'optimize'
        })

    # Check for very large tables (>100MB)
    large_tables = [t for t in tables if t.size_mb > 100]
    if large_tables:
        suggestions.append({
            'type': 'large_tables',
            'severity': 'info',
            'title': f'{len(large_tables)} large table(s) detected',
            'message': 'Large tables may benefit from archiving old data or adding indexes.',
            'tables': [f"{t.name} ({t.size_mb} MB)" for t in large_tables[:3]],
            'action': 'review'
        })

    # Check for tables with many rows but low size (potential bloat)
    for table in tables:
        if table.rows > 100000 and table.size_mb < 10:
            # Many rows but small size - could indicate data issues
            pass  # Skip for now, this is an advanced optimization

    # If no issues found
    if not suggestions:
        suggestions.append({
            'type': 'healthy',
            'severity': 'success',
            'title': 'Database tables are healthy',
            'message': 'No optimization needed. Tables are performing well.',
            'tables': [],
            'action': None
        })

    return suggestions


# =============================================================================
# Public API Functions
# =============================================================================

def analyze_tables(customer_id: int) -> Dict[str, Any]:
    """
    Analyze all tables for a customer and return comprehensive statistics.

    This is the main public API function for table analysis.

    Args:
        customer_id: The customer ID to analyze

    Returns:
        Dictionary with table stats, summary, and suggestions:
        {
            'success': bool,
            'tables': [...],
            'summary': {
                'total_tables': int,
                'total_size_mb': float,
                'fragmented_count': int,
                'total_rows': int
            },
            'suggestions': [...],
            'error': str (only if success=False)
        }
    """
    success, result = get_table_stats(customer_id)

    if not success:
        return {
            'success': False,
            'error': result,
            'tables': [],
            'summary': None,
            'suggestions': []
        }

    tables = result

    # Calculate summary statistics
    summary = {
        'total_tables': len(tables),
        'total_size_mb': round(sum(t.size_mb for t in tables), 2),
        'fragmented_count': sum(1 for t in tables if t.needs_optimization),
        'total_rows': sum(t.rows for t in tables),
        'total_data_free_mb': round(sum(t.data_free for t in tables) / (1024 * 1024), 2)
    }

    # Generate suggestions
    suggestions = get_optimization_suggestions(tables)

    return {
        'success': True,
        'tables': [t.to_dict() for t in tables],
        'summary': summary,
        'suggestions': suggestions
    }


def run_table_optimization(customer_id: int, table_name: str) -> Dict[str, Any]:
    """
    Run OPTIMIZE TABLE on a specific table for a customer.

    Args:
        customer_id: The customer ID
        table_name: The table to optimize

    Returns:
        Dictionary with result:
        {
            'success': bool,
            'message': str,
            'table_name': str
        }
    """
    success, message = optimize_table(customer_id, table_name)

    return {
        'success': success,
        'message': message,
        'table_name': table_name
    }
