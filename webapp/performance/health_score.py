"""
ShopHosting.io - Health Score Calculation Module

Calculates a weighted health score (0-100) for customer sites based on:
- Page Speed (30%): TTFB, LCP, FCP thresholds
- Resource Usage (25%): CPU %, Memory %, Disk % vs plan limits
- Database Health (20%): Slow query count, connection usage ratio
- Cache Efficiency (15%): Redis hit rate, Varnish hit rate (Magento)
- Uptime (10%): Last 24h availability percentage

Scoring logic per factor:
- 100: Excellent (green)
- 80-99: Good (green)
- 50-79: Warning (yellow)
- 0-49: Critical (red)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Thresholds Configuration
# =============================================================================

# Page Speed thresholds (in milliseconds)
# Based on Web Vitals recommendations
TTFB_THRESHOLDS = {
    'excellent': 200,   # < 200ms is excellent
    'good': 500,        # < 500ms is good
    'warning': 1500,    # < 1500ms is acceptable
    'critical': 3000,   # >= 3000ms is critical
}

LCP_THRESHOLDS = {
    'excellent': 1000,  # < 1s is excellent
    'good': 2500,       # < 2.5s is good (Google's threshold)
    'warning': 4000,    # < 4s is acceptable
    'critical': 6000,   # >= 6s is critical
}

FCP_THRESHOLDS = {
    'excellent': 500,   # < 500ms is excellent
    'good': 1800,       # < 1.8s is good (Google's threshold)
    'warning': 3000,    # < 3s is acceptable
    'critical': 5000,   # >= 5s is critical
}

# Resource Usage thresholds (percentage)
RESOURCE_THRESHOLDS = {
    'excellent': 50,    # < 50% is excellent
    'good': 70,         # < 70% is good
    'warning': 85,      # < 85% is acceptable
    'critical': 95,     # >= 95% is critical
}

# Database Health thresholds
SLOW_QUERY_THRESHOLDS = {
    'excellent': 0,     # 0 slow queries is excellent
    'good': 2,          # 1-2 slow queries is good
    'warning': 5,       # 3-5 slow queries is acceptable
    'critical': 10,     # > 10 slow queries is critical
}

CONNECTION_RATIO_THRESHOLDS = {
    'excellent': 30,    # < 30% of max connections
    'good': 50,         # < 50% is good
    'warning': 70,      # < 70% is acceptable
    'critical': 90,     # >= 90% is critical
}

# Default max connections for MySQL
DEFAULT_MAX_CONNECTIONS = 100

# Cache Efficiency thresholds (hit rate percentage)
CACHE_HIT_THRESHOLDS = {
    'excellent': 95,    # >= 95% hit rate is excellent
    'good': 85,         # >= 85% is good
    'warning': 70,      # >= 70% is acceptable
    'critical': 50,     # < 50% is critical
}

# Uptime thresholds (percentage)
UPTIME_THRESHOLDS = {
    'excellent': 99.9,  # >= 99.9% is excellent
    'good': 99.0,       # >= 99% is good
    'warning': 95.0,    # >= 95% is acceptable
    'critical': 90.0,   # < 90% is critical
}

# Weight configuration for final score
FACTOR_WEIGHTS = {
    'page_speed': 0.30,
    'resource_usage': 0.25,
    'database_health': 0.20,
    'cache_efficiency': 0.15,
    'uptime': 0.10,
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class FactorScore:
    """Score for a single health factor"""
    name: str
    score: int  # 0-100
    status: str  # 'excellent', 'good', 'warning', 'critical', 'unknown'
    details: Dict[str, Any] = field(default_factory=dict)
    weight: float = 0.0
    data_available: bool = True

    @property
    def color(self) -> str:
        """Return color based on status"""
        if self.status in ('excellent', 'good'):
            return 'green'
        elif self.status == 'warning':
            return 'yellow'
        elif self.status == 'critical':
            return 'red'
        return 'gray'  # unknown


@dataclass
class HealthScoreResult:
    """Complete health score result with breakdown"""
    customer_id: int
    overall_score: int  # 0-100
    overall_status: str  # 'excellent', 'good', 'warning', 'critical'
    factors: Dict[str, FactorScore]
    calculated_at: datetime = field(default_factory=datetime.now)
    data_freshness: Optional[datetime] = None  # Timestamp of latest data used

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses"""
        return {
            'customer_id': self.customer_id,
            'overall_score': self.overall_score,
            'overall_status': self.overall_status,
            'overall_color': self._get_color(self.overall_status),
            'calculated_at': self.calculated_at.isoformat(),
            'data_freshness': self.data_freshness.isoformat() if self.data_freshness else None,
            'factors': {
                name: {
                    'score': factor.score,
                    'status': factor.status,
                    'color': factor.color,
                    'weight': factor.weight,
                    'weight_percent': int(factor.weight * 100),
                    'data_available': factor.data_available,
                    'details': factor.details,
                }
                for name, factor in self.factors.items()
            }
        }

    @staticmethod
    def _get_color(status: str) -> str:
        if status in ('excellent', 'good'):
            return 'green'
        elif status == 'warning':
            return 'yellow'
        elif status == 'critical':
            return 'red'
        return 'gray'


# =============================================================================
# Health Score Calculator
# =============================================================================

class HealthScoreCalculator:
    """
    Calculates health scores for customer sites based on multiple factors.

    Uses data from:
    - performance_snapshots table (metrics collected by monitoring_worker)
    - monitoring_status table (uptime and current status)
    - customers table (plan limits)
    """

    def __init__(self, db_connection_func=None):
        """
        Initialize the calculator.

        Args:
            db_connection_func: Function that returns a database connection.
                              If None, will import from models.
        """
        self._get_db_connection = db_connection_func

    def _get_connection(self):
        """Get database connection"""
        if self._get_db_connection:
            return self._get_db_connection()
        from webapp.models import get_db_connection
        return get_db_connection(read_only=True)

    def calculate(self, customer_id: int) -> HealthScoreResult:
        """
        Calculate health score for a customer.

        Args:
            customer_id: The customer ID to calculate score for

        Returns:
            HealthScoreResult with overall score and factor breakdown
        """
        # Fetch all required data
        snapshot = self._get_latest_snapshot(customer_id)
        monitoring_status = self._get_monitoring_status(customer_id)
        plan_limits = self._get_plan_limits(customer_id)
        customer_platform = self._get_customer_platform(customer_id)

        # Calculate each factor
        factors = {}

        # Page Speed (30%)
        factors['page_speed'] = self._calculate_page_speed_score(snapshot)

        # Resource Usage (25%)
        factors['resource_usage'] = self._calculate_resource_score(
            snapshot, monitoring_status, plan_limits
        )

        # Database Health (20%)
        factors['database_health'] = self._calculate_database_score(
            snapshot, plan_limits
        )

        # Cache Efficiency (15%)
        factors['cache_efficiency'] = self._calculate_cache_score(
            snapshot, customer_platform
        )

        # Uptime (10%)
        factors['uptime'] = self._calculate_uptime_score(monitoring_status)

        # Calculate overall score with dynamic weight adjustment
        overall_score, effective_weights = self._calculate_overall_score(factors)
        overall_status = self._score_to_status(overall_score)

        # Update weights in factors to reflect actual weights used
        for name, factor in factors.items():
            factor.weight = effective_weights.get(name, 0.0)

        # Determine data freshness
        data_freshness = None
        if snapshot and snapshot.get('timestamp'):
            data_freshness = snapshot['timestamp']

        return HealthScoreResult(
            customer_id=customer_id,
            overall_score=overall_score,
            overall_status=overall_status,
            factors=factors,
            data_freshness=data_freshness
        )

    def _get_latest_snapshot(self, customer_id: int) -> Optional[Dict[str, Any]]:
        """Get the most recent performance snapshot for a customer"""
        conn = self._get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("""
                SELECT * FROM performance_snapshots
                WHERE customer_id = %s
                ORDER BY timestamp DESC
                LIMIT 1
            """, (customer_id,))
            return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error fetching snapshot for customer {customer_id}: {e}")
            return None
        finally:
            cursor.close()
            conn.close()

    def _get_monitoring_status(self, customer_id: int) -> Optional[Dict[str, Any]]:
        """Get current monitoring status for a customer"""
        conn = self._get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("""
                SELECT * FROM customer_monitoring_status
                WHERE customer_id = %s
            """, (customer_id,))
            return cursor.fetchone()
        except Exception as e:
            logger.error(f"Error fetching monitoring status for customer {customer_id}: {e}")
            return None
        finally:
            cursor.close()
            conn.close()

    def _get_plan_limits(self, customer_id: int) -> Optional[Dict[str, Any]]:
        """Get plan limits for a customer"""
        conn = self._get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("""
                SELECT pp.memory_limit, pp.cpu_limit, pp.disk_limit_gb
                FROM customers c
                JOIN pricing_plans pp ON c.plan_id = pp.id
                WHERE c.id = %s
            """, (customer_id,))
            return cursor.fetchone()
        except Exception as e:
            logger.debug(f"Could not fetch plan limits for customer {customer_id}: {e}")
            return None
        finally:
            cursor.close()
            conn.close()

    def _get_customer_platform(self, customer_id: int) -> Optional[str]:
        """Get customer's platform (woocommerce or magento)"""
        conn = self._get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("""
                SELECT platform FROM customers WHERE id = %s
            """, (customer_id,))
            row = cursor.fetchone()
            return row['platform'] if row else None
        except Exception as e:
            logger.debug(f"Could not fetch platform for customer {customer_id}: {e}")
            return None
        finally:
            cursor.close()
            conn.close()

    def _calculate_page_speed_score(
        self, snapshot: Optional[Dict[str, Any]]
    ) -> FactorScore:
        """
        Calculate Page Speed factor score (30% weight).
        Based on TTFB, LCP, and FCP metrics.
        """
        if not snapshot:
            return FactorScore(
                name='Page Speed',
                score=0,
                status='unknown',
                details={'message': 'No performance data available'},
                data_available=False
            )

        ttfb = snapshot.get('ttfb_ms')
        lcp = snapshot.get('lcp_ms')
        fcp = snapshot.get('fcp_ms')

        sub_scores = []
        details = {}

        # TTFB scoring (most important for server performance)
        if ttfb is not None:
            ttfb_score = self._metric_to_score(
                ttfb, TTFB_THRESHOLDS, lower_is_better=True
            )
            sub_scores.append(('ttfb', ttfb_score, 0.5))  # 50% weight within page speed
            details['ttfb_ms'] = ttfb
            details['ttfb_score'] = ttfb_score
            details['ttfb_status'] = self._score_to_status(ttfb_score)

        # LCP scoring
        if lcp is not None:
            lcp_score = self._metric_to_score(
                lcp, LCP_THRESHOLDS, lower_is_better=True
            )
            sub_scores.append(('lcp', lcp_score, 0.3))  # 30% weight within page speed
            details['lcp_ms'] = lcp
            details['lcp_score'] = lcp_score
            details['lcp_status'] = self._score_to_status(lcp_score)

        # FCP scoring
        if fcp is not None:
            fcp_score = self._metric_to_score(
                fcp, FCP_THRESHOLDS, lower_is_better=True
            )
            sub_scores.append(('fcp', fcp_score, 0.2))  # 20% weight within page speed
            details['fcp_ms'] = fcp
            details['fcp_score'] = fcp_score
            details['fcp_status'] = self._score_to_status(fcp_score)

        if not sub_scores:
            return FactorScore(
                name='Page Speed',
                score=0,
                status='unknown',
                details={'message': 'No page speed metrics available'},
                data_available=False
            )

        # Calculate weighted average, normalizing weights
        total_weight = sum(w for _, _, w in sub_scores)
        final_score = int(round(
            sum(score * weight for _, score, weight in sub_scores) / total_weight
        ))

        return FactorScore(
            name='Page Speed',
            score=final_score,
            status=self._score_to_status(final_score),
            details=details
        )

    def _calculate_resource_score(
        self,
        snapshot: Optional[Dict[str, Any]],
        monitoring_status: Optional[Dict[str, Any]],
        plan_limits: Optional[Dict[str, Any]]
    ) -> FactorScore:
        """
        Calculate Resource Usage factor score (25% weight).
        Based on CPU %, Memory %, and Disk % vs plan limits.
        """
        sub_scores = []
        details = {}

        # Get CPU percentage - prefer snapshot, fall back to monitoring status
        cpu_percent = None
        if snapshot and snapshot.get('cpu_percent') is not None:
            cpu_percent = float(snapshot['cpu_percent'])
        elif monitoring_status and monitoring_status.get('cpu_percent') is not None:
            cpu_percent = float(monitoring_status['cpu_percent'])

        if cpu_percent is not None:
            cpu_score = self._metric_to_score(
                cpu_percent, RESOURCE_THRESHOLDS, lower_is_better=True
            )
            sub_scores.append(('cpu', cpu_score, 0.35))  # 35% weight
            details['cpu_percent'] = round(cpu_percent, 1)
            details['cpu_score'] = cpu_score
            details['cpu_status'] = self._score_to_status(cpu_score)

        # Get Memory percentage - prefer snapshot, fall back to monitoring status
        memory_percent = None
        if snapshot and snapshot.get('memory_percent') is not None:
            memory_percent = float(snapshot['memory_percent'])
        elif monitoring_status and monitoring_status.get('memory_percent') is not None:
            memory_percent = float(monitoring_status['memory_percent'])

        if memory_percent is not None:
            memory_score = self._metric_to_score(
                memory_percent, RESOURCE_THRESHOLDS, lower_is_better=True
            )
            sub_scores.append(('memory', memory_score, 0.35))  # 35% weight
            details['memory_percent'] = round(memory_percent, 1)
            details['memory_score'] = memory_score
            details['memory_status'] = self._score_to_status(memory_score)

        # Get Disk percentage
        disk_percent = None
        if snapshot and snapshot.get('disk_percent') is not None:
            disk_percent = float(snapshot['disk_percent'])

        if disk_percent is not None:
            disk_score = self._metric_to_score(
                disk_percent, RESOURCE_THRESHOLDS, lower_is_better=True
            )
            sub_scores.append(('disk', disk_score, 0.30))  # 30% weight
            details['disk_percent'] = round(disk_percent, 1)
            details['disk_score'] = disk_score
            details['disk_status'] = self._score_to_status(disk_score)

        if not sub_scores:
            return FactorScore(
                name='Resource Usage',
                score=0,
                status='unknown',
                details={'message': 'No resource metrics available'},
                data_available=False
            )

        # Calculate weighted average, normalizing weights
        total_weight = sum(w for _, _, w in sub_scores)
        final_score = int(round(
            sum(score * weight for _, score, weight in sub_scores) / total_weight
        ))

        return FactorScore(
            name='Resource Usage',
            score=final_score,
            status=self._score_to_status(final_score),
            details=details
        )

    def _calculate_database_score(
        self,
        snapshot: Optional[Dict[str, Any]],
        plan_limits: Optional[Dict[str, Any]]
    ) -> FactorScore:
        """
        Calculate Database Health factor score (20% weight).
        Based on slow query count and connection usage ratio.
        """
        if not snapshot:
            return FactorScore(
                name='Database Health',
                score=0,
                status='unknown',
                details={'message': 'No database metrics available'},
                data_available=False
            )

        sub_scores = []
        details = {}

        # Slow query count scoring
        slow_query_count = snapshot.get('slow_query_count')
        if slow_query_count is not None:
            # Invert the threshold logic for slow queries (0 is best)
            sq_score = self._slow_query_to_score(slow_query_count)
            sub_scores.append(('slow_queries', sq_score, 0.6))  # 60% weight
            details['slow_query_count'] = slow_query_count
            details['slow_query_score'] = sq_score
            details['slow_query_status'] = self._score_to_status(sq_score)

        # Connection usage ratio scoring
        active_connections = snapshot.get('active_connections')
        if active_connections is not None:
            # Calculate ratio vs max connections
            max_connections = DEFAULT_MAX_CONNECTIONS
            connection_ratio = (active_connections / max_connections) * 100
            conn_score = self._metric_to_score(
                connection_ratio, CONNECTION_RATIO_THRESHOLDS, lower_is_better=True
            )
            sub_scores.append(('connections', conn_score, 0.4))  # 40% weight
            details['active_connections'] = active_connections
            details['max_connections'] = max_connections
            details['connection_ratio'] = round(connection_ratio, 1)
            details['connection_score'] = conn_score
            details['connection_status'] = self._score_to_status(conn_score)

        if not sub_scores:
            return FactorScore(
                name='Database Health',
                score=0,
                status='unknown',
                details={'message': 'No database metrics available'},
                data_available=False
            )

        # Calculate weighted average
        total_weight = sum(w for _, _, w in sub_scores)
        final_score = int(round(
            sum(score * weight for _, score, weight in sub_scores) / total_weight
        ))

        return FactorScore(
            name='Database Health',
            score=final_score,
            status=self._score_to_status(final_score),
            details=details
        )

    def _calculate_cache_score(
        self,
        snapshot: Optional[Dict[str, Any]],
        platform: Optional[str]
    ) -> FactorScore:
        """
        Calculate Cache Efficiency factor score (15% weight).
        Based on Redis hit rate and Varnish hit rate (Magento only).
        """
        if not snapshot:
            return FactorScore(
                name='Cache Efficiency',
                score=0,
                status='unknown',
                details={'message': 'No cache metrics available'},
                data_available=False
            )

        sub_scores = []
        details = {}
        is_magento = platform and platform.lower() == 'magento'

        # Redis hit rate scoring
        redis_hit_rate = snapshot.get('redis_hit_rate')
        if redis_hit_rate is not None:
            redis_hit_rate = float(redis_hit_rate)
            redis_score = self._cache_hit_to_score(redis_hit_rate)
            # Redis weight depends on whether Varnish is expected
            redis_weight = 0.5 if is_magento else 1.0
            sub_scores.append(('redis', redis_score, redis_weight))
            details['redis_hit_rate'] = round(redis_hit_rate, 1)
            details['redis_score'] = redis_score
            details['redis_status'] = self._score_to_status(redis_score)

        # Varnish hit rate scoring (Magento only)
        varnish_hit_rate = snapshot.get('varnish_hit_rate')
        if varnish_hit_rate is not None and is_magento:
            varnish_hit_rate = float(varnish_hit_rate)
            varnish_score = self._cache_hit_to_score(varnish_hit_rate)
            sub_scores.append(('varnish', varnish_score, 0.5))
            details['varnish_hit_rate'] = round(varnish_hit_rate, 1)
            details['varnish_score'] = varnish_score
            details['varnish_status'] = self._score_to_status(varnish_score)

        details['is_magento'] = is_magento

        if not sub_scores:
            return FactorScore(
                name='Cache Efficiency',
                score=0,
                status='unknown',
                details={'message': 'No cache metrics available'},
                data_available=False
            )

        # Calculate weighted average
        total_weight = sum(w for _, _, w in sub_scores)
        final_score = int(round(
            sum(score * weight for _, score, weight in sub_scores) / total_weight
        ))

        return FactorScore(
            name='Cache Efficiency',
            score=final_score,
            status=self._score_to_status(final_score),
            details=details
        )

    def _calculate_uptime_score(
        self, monitoring_status: Optional[Dict[str, Any]]
    ) -> FactorScore:
        """
        Calculate Uptime factor score (10% weight).
        Based on last 24h availability percentage.
        """
        if not monitoring_status:
            return FactorScore(
                name='Uptime',
                score=0,
                status='unknown',
                details={'message': 'No uptime data available'},
                data_available=False
            )

        uptime_24h = monitoring_status.get('uptime_24h')
        if uptime_24h is None:
            return FactorScore(
                name='Uptime',
                score=0,
                status='unknown',
                details={'message': 'No uptime data available'},
                data_available=False
            )

        uptime_24h = float(uptime_24h)
        uptime_score = self._uptime_to_score(uptime_24h)

        details = {
            'uptime_24h': round(uptime_24h, 2),
            'uptime_score': uptime_score,
            'uptime_status': self._score_to_status(uptime_score),
        }

        # Add current status info
        details['http_status'] = monitoring_status.get('http_status', 'unknown')
        details['container_status'] = monitoring_status.get('container_status', 'unknown')

        return FactorScore(
            name='Uptime',
            score=uptime_score,
            status=self._score_to_status(uptime_score),
            details=details
        )

    def _calculate_overall_score(
        self, factors: Dict[str, FactorScore]
    ) -> Tuple[int, Dict[str, float]]:
        """
        Calculate overall score with dynamic weight adjustment.

        If a factor has no data available, redistribute its weight
        proportionally among factors that do have data.

        Returns:
            Tuple of (overall_score, effective_weights_dict)
        """
        available_factors = {
            name: factor for name, factor in factors.items()
            if factor.data_available
        }

        if not available_factors:
            # No data at all - return 0
            return 0, {name: 0.0 for name in FACTOR_WEIGHTS}

        # Calculate total weight of available factors
        available_weight = sum(
            FACTOR_WEIGHTS[name] for name in available_factors
        )

        # Calculate effective weights (redistributed)
        effective_weights = {}
        for name in FACTOR_WEIGHTS:
            if name in available_factors:
                # Scale up weight proportionally
                effective_weights[name] = FACTOR_WEIGHTS[name] / available_weight
            else:
                effective_weights[name] = 0.0

        # Calculate weighted score
        total_score = sum(
            factors[name].score * effective_weights[name]
            for name in available_factors
        )

        return int(round(total_score)), effective_weights

    def _metric_to_score(
        self,
        value: float,
        thresholds: Dict[str, float],
        lower_is_better: bool = True
    ) -> int:
        """
        Convert a metric value to a 0-100 score based on thresholds.

        Args:
            value: The metric value
            thresholds: Dict with 'excellent', 'good', 'warning', 'critical' keys
            lower_is_better: If True, lower values get higher scores
        """
        if lower_is_better:
            if value <= thresholds['excellent']:
                return 100
            elif value <= thresholds['good']:
                # Linear interpolation between 80-100
                ratio = (value - thresholds['excellent']) / (
                    thresholds['good'] - thresholds['excellent']
                )
                return int(100 - (ratio * 20))
            elif value <= thresholds['warning']:
                # Linear interpolation between 50-79
                ratio = (value - thresholds['good']) / (
                    thresholds['warning'] - thresholds['good']
                )
                return int(80 - (ratio * 30))
            elif value <= thresholds['critical']:
                # Linear interpolation between 0-49
                ratio = (value - thresholds['warning']) / (
                    thresholds['critical'] - thresholds['warning']
                )
                return int(50 - (ratio * 50))
            else:
                return 0
        else:
            # Higher is better (used for cache hit rates, uptime)
            if value >= thresholds['excellent']:
                return 100
            elif value >= thresholds['good']:
                ratio = (thresholds['excellent'] - value) / (
                    thresholds['excellent'] - thresholds['good']
                )
                return int(100 - (ratio * 20))
            elif value >= thresholds['warning']:
                ratio = (thresholds['good'] - value) / (
                    thresholds['good'] - thresholds['warning']
                )
                return int(80 - (ratio * 30))
            elif value >= thresholds['critical']:
                ratio = (thresholds['warning'] - value) / (
                    thresholds['warning'] - thresholds['critical']
                )
                return int(50 - (ratio * 50))
            else:
                return 0

    def _slow_query_to_score(self, count: int) -> int:
        """Convert slow query count to score (0 queries = 100, more = lower)"""
        if count <= SLOW_QUERY_THRESHOLDS['excellent']:
            return 100
        elif count <= SLOW_QUERY_THRESHOLDS['good']:
            return 90
        elif count <= SLOW_QUERY_THRESHOLDS['warning']:
            # Linear interpolation between 50-89
            ratio = (count - SLOW_QUERY_THRESHOLDS['good']) / (
                SLOW_QUERY_THRESHOLDS['warning'] - SLOW_QUERY_THRESHOLDS['good']
            )
            return int(90 - (ratio * 40))
        elif count <= SLOW_QUERY_THRESHOLDS['critical']:
            # Linear interpolation between 0-49
            ratio = (count - SLOW_QUERY_THRESHOLDS['warning']) / (
                SLOW_QUERY_THRESHOLDS['critical'] - SLOW_QUERY_THRESHOLDS['warning']
            )
            return int(50 - (ratio * 50))
        else:
            return 0

    def _cache_hit_to_score(self, hit_rate: float) -> int:
        """Convert cache hit rate to score (higher is better)"""
        return self._metric_to_score(
            hit_rate, CACHE_HIT_THRESHOLDS, lower_is_better=False
        )

    def _uptime_to_score(self, uptime_percent: float) -> int:
        """Convert uptime percentage to score"""
        return self._metric_to_score(
            uptime_percent, UPTIME_THRESHOLDS, lower_is_better=False
        )

    @staticmethod
    def _score_to_status(score: int) -> str:
        """Convert numeric score to status string"""
        if score >= 100:
            return 'excellent'
        elif score >= 80:
            return 'good'
        elif score >= 50:
            return 'warning'
        else:
            return 'critical'


# =============================================================================
# Public API Function
# =============================================================================

def calculate_health_score(customer_id: int) -> Dict[str, Any]:
    """
    Calculate health score for a customer.

    This is the main public API function that creates a calculator
    instance and returns the score as a dictionary.

    Args:
        customer_id: The customer ID to calculate score for

    Returns:
        Dictionary with overall score, status, and factor breakdown:
        {
            'customer_id': int,
            'overall_score': int (0-100),
            'overall_status': str ('excellent'|'good'|'warning'|'critical'),
            'overall_color': str ('green'|'yellow'|'red'),
            'calculated_at': str (ISO timestamp),
            'data_freshness': str (ISO timestamp) or None,
            'factors': {
                'page_speed': { score, status, color, weight, details, ... },
                'resource_usage': { ... },
                'database_health': { ... },
                'cache_efficiency': { ... },
                'uptime': { ... },
            }
        }
    """
    calculator = HealthScoreCalculator()
    result = calculator.calculate(customer_id)
    return result.to_dict()


def get_health_score_with_trend(customer_id: int) -> Dict[str, Any]:
    """
    Calculate health score for a customer including trend vs 24 hours ago.

    This function extends calculate_health_score by adding:
    - trend: 'up', 'down', or 'stable' compared to 24h ago
    - previous_score: The score from ~24h ago (or None if not available)
    - score_change: The numerical difference from previous score

    Args:
        customer_id: The customer ID to calculate score for

    Returns:
        Dictionary with score, trend information, and factor breakdown
    """
    calculator = HealthScoreCalculator()

    # Get current score
    current_result = calculator.calculate(customer_id)
    result = current_result.to_dict()

    # Rename for API consistency
    result['score'] = result.pop('overall_score')
    result['status'] = result.pop('overall_status')
    result['color'] = result.pop('overall_color')
    result['updated_at'] = result.pop('calculated_at')

    # Get score from 24 hours ago
    previous_score = _get_score_24h_ago(customer_id, calculator)

    # Calculate trend
    if previous_score is not None:
        score_change = result['score'] - previous_score
        if score_change > 2:
            trend = 'up'
        elif score_change < -2:
            trend = 'down'
        else:
            trend = 'stable'
        result['trend'] = trend
        result['previous_score'] = previous_score
        result['score_change'] = score_change
    else:
        result['trend'] = 'stable'  # No previous data, default to stable
        result['previous_score'] = None
        result['score_change'] = 0

    return result


def _get_score_24h_ago(customer_id: int, calculator: HealthScoreCalculator) -> Optional[int]:
    """
    Get the health score from approximately 24 hours ago.

    Looks for a performance snapshot from ~24h ago and calculates
    what the score would have been with that data.

    Args:
        customer_id: The customer ID
        calculator: HealthScoreCalculator instance to use

    Returns:
        The health score from 24h ago, or None if no data available
    """
    conn = calculator._get_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        # Get snapshot from approximately 24 hours ago (within a 2 hour window)
        cursor.execute("""
            SELECT health_score FROM performance_snapshots
            WHERE customer_id = %s
              AND timestamp >= DATE_SUB(NOW(), INTERVAL 26 HOUR)
              AND timestamp <= DATE_SUB(NOW(), INTERVAL 22 HOUR)
            ORDER BY timestamp DESC
            LIMIT 1
        """, (customer_id,))
        row = cursor.fetchone()

        if row and row.get('health_score') is not None:
            return int(row['health_score'])

        # If no snapshot with stored score, try to find one and calculate
        # This is a fallback for older snapshots without pre-computed scores
        cursor.execute("""
            SELECT * FROM performance_snapshots
            WHERE customer_id = %s
              AND timestamp >= DATE_SUB(NOW(), INTERVAL 26 HOUR)
              AND timestamp <= DATE_SUB(NOW(), INTERVAL 22 HOUR)
            ORDER BY timestamp DESC
            LIMIT 1
        """, (customer_id,))
        snapshot = cursor.fetchone()

        if not snapshot:
            return None

        # Calculate score from historical snapshot data
        # This is a simplified calculation using available metrics
        scores = []
        weights = []

        # Page speed metrics
        if snapshot.get('ttfb_ms') is not None:
            ttfb_score = calculator._metric_to_score(
                snapshot['ttfb_ms'], TTFB_THRESHOLDS, lower_is_better=True
            )
            scores.append(ttfb_score)
            weights.append(FACTOR_WEIGHTS['page_speed'])

        # Resource usage
        resource_scores = []
        if snapshot.get('cpu_percent') is not None:
            resource_scores.append(calculator._metric_to_score(
                float(snapshot['cpu_percent']), RESOURCE_THRESHOLDS, lower_is_better=True
            ))
        if snapshot.get('memory_percent') is not None:
            resource_scores.append(calculator._metric_to_score(
                float(snapshot['memory_percent']), RESOURCE_THRESHOLDS, lower_is_better=True
            ))
        if resource_scores:
            scores.append(sum(resource_scores) / len(resource_scores))
            weights.append(FACTOR_WEIGHTS['resource_usage'])

        # Database health
        if snapshot.get('slow_query_count') is not None:
            db_score = calculator._slow_query_to_score(snapshot['slow_query_count'])
            scores.append(db_score)
            weights.append(FACTOR_WEIGHTS['database_health'])

        # Cache efficiency
        if snapshot.get('redis_hit_rate') is not None:
            cache_score = calculator._cache_hit_to_score(float(snapshot['redis_hit_rate']))
            scores.append(cache_score)
            weights.append(FACTOR_WEIGHTS['cache_efficiency'])

        if not scores:
            return None

        # Calculate weighted average
        total_weight = sum(weights)
        weighted_score = sum(s * w for s, w in zip(scores, weights)) / total_weight
        return int(round(weighted_score))

    except Exception as e:
        logger.error(f"Error getting 24h ago score for customer {customer_id}: {e}")
        return None
    finally:
        cursor.close()
        conn.close()
