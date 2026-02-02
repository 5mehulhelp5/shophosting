"""
Comparative Benchmarking for ShopHosting.io Admin Console

Compares each store's performance against similar stores in the same cohort.

Cohort Definition:
- Same platform (WooCommerce/Magento)
- Similar plan tier (single/multi)

Metrics Benchmarked:
- health_score: Overall health (higher is better)
- cpu_percent: CPU usage (lower is better)
- memory_percent: Memory usage (lower is better)
- ttfb_ms: Time to First Byte (lower is better)
- slow_query_count: Number of slow queries (lower is better)
- redis_hit_rate: Redis cache efficiency (higher is better)
"""

import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkResult:
    """Result of benchmarking a single metric against the cohort."""
    metric_name: str
    customer_value: float
    cohort_avg: float
    cohort_best: float
    cohort_worst: float
    percentile: int  # 0-100, higher is better

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            'metric_name': self.metric_name,
            'customer_value': self.customer_value,
            'cohort_avg': round(self.cohort_avg, 2),
            'cohort_best': self.cohort_best,
            'cohort_worst': self.cohort_worst,
            'percentile': self.percentile,
            'vs_avg': self._get_comparison_to_avg(),
            'rating': self._get_rating(),
        }

    def _get_comparison_to_avg(self) -> str:
        """Get human-readable comparison to cohort average."""
        if self.cohort_avg == 0:
            return 'N/A'
        diff = self.customer_value - self.cohort_avg
        pct = (diff / self.cohort_avg) * 100
        if abs(pct) < 1:
            return 'same as average'
        elif pct > 0:
            return f'{abs(pct):.0f}% above average'
        else:
            return f'{abs(pct):.0f}% below average'

    def _get_rating(self) -> str:
        """Get rating based on percentile."""
        if self.percentile >= 90:
            return 'excellent'
        elif self.percentile >= 70:
            return 'good'
        elif self.percentile >= 40:
            return 'average'
        elif self.percentile >= 20:
            return 'below_average'
        else:
            return 'poor'


# Define which metrics are "lower is better" vs "higher is better"
LOWER_IS_BETTER_METRICS = {
    'cpu_percent',
    'memory_percent',
    'ttfb_ms',
    'slow_query_count',
}

HIGHER_IS_BETTER_METRICS = {
    'health_score',
    'redis_hit_rate',
}


class CohortBenchmarker:
    """Compares customer metrics against their cohort."""

    def __init__(self, customer_id: int, db_connection_func=None):
        """
        Initialize the benchmarker.

        Args:
            customer_id: The customer ID to benchmark
            db_connection_func: Function that returns a database connection.
                              If None, will import from models.
        """
        self.customer_id = customer_id
        self._get_db_connection = db_connection_func
        self.customer = None
        self.cohort_customer_ids: List[int] = []
        self._loaded = False

    def _get_connection(self):
        """Get database connection."""
        if self._get_db_connection:
            return self._get_db_connection()
        from webapp.models import get_db_connection
        return get_db_connection(read_only=True)

    def _ensure_loaded(self):
        """Ensure customer and cohort data is loaded."""
        if not self._loaded:
            self._load_customer()
            self._find_cohort()
            self._loaded = True

    def _load_customer(self):
        """Load customer details."""
        conn = self._get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute("""
                SELECT c.id, c.platform, c.plan_id, pp.tier_type, pp.slug as plan_slug
                FROM customers c
                LEFT JOIN pricing_plans pp ON c.plan_id = pp.id
                WHERE c.id = %s AND c.status = 'active'
            """, (self.customer_id,))
            self.customer = cursor.fetchone()

            if not self.customer:
                logger.warning(f"Customer {self.customer_id} not found or not active")

        except Exception as e:
            logger.error(f"Error loading customer {self.customer_id}: {e}")
            self.customer = None
        finally:
            cursor.close()
            conn.close()

    def _find_cohort(self) -> List[int]:
        """
        Find similar customers (same platform, similar tier).

        Cohort criteria:
        - Same platform (WooCommerce/Magento)
        - Similar plan tier (single/multi)
        - Active status
        - Has performance data within last 24 hours

        Returns list of customer IDs in the cohort.
        """
        if not self.customer:
            self.cohort_customer_ids = []
            return self.cohort_customer_ids

        conn = self._get_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            platform = self.customer.get('platform')
            tier_type = self.customer.get('tier_type')

            # Find cohort members with recent performance data
            cursor.execute("""
                SELECT DISTINCT c.id
                FROM customers c
                LEFT JOIN pricing_plans pp ON c.plan_id = pp.id
                INNER JOIN performance_snapshots ps ON c.id = ps.customer_id
                WHERE c.status = 'active'
                  AND c.platform = %s
                  AND (pp.tier_type = %s OR (pp.tier_type IS NULL AND %s IS NULL))
                  AND ps.timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
                ORDER BY c.id
            """, (platform, tier_type, tier_type))

            rows = cursor.fetchall()
            self.cohort_customer_ids = [row['id'] for row in rows]

            logger.debug(
                f"Found {len(self.cohort_customer_ids)} cohort members for customer "
                f"{self.customer_id} (platform={platform}, tier={tier_type})"
            )

        except Exception as e:
            logger.error(f"Error finding cohort for customer {self.customer_id}: {e}")
            self.cohort_customer_ids = []
        finally:
            cursor.close()
            conn.close()

        return self.cohort_customer_ids

    def get_benchmarks(self) -> Dict[str, BenchmarkResult]:
        """
        Get benchmark comparisons for key metrics.

        Metrics to benchmark:
        - health_score (higher is better)
        - cpu_percent (lower is better)
        - memory_percent (lower is better)
        - ttfb_ms (lower is better)
        - slow_query_count (lower is better)
        - redis_hit_rate (higher is better)

        Returns dict of metric_name -> BenchmarkResult
        """
        self._ensure_loaded()

        if not self.customer or not self.cohort_customer_ids:
            return {}

        conn = self._get_connection()
        cursor = conn.cursor(dictionary=True)
        results: Dict[str, BenchmarkResult] = {}

        try:
            # Get latest metrics for all cohort members (including target customer)
            cohort_ids_str = ','.join(str(cid) for cid in self.cohort_customer_ids)

            # Query to get latest snapshot per customer
            cursor.execute(f"""
                SELECT ps.*
                FROM performance_snapshots ps
                INNER JOIN (
                    SELECT customer_id, MAX(timestamp) as max_ts
                    FROM performance_snapshots
                    WHERE customer_id IN ({cohort_ids_str})
                      AND timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
                    GROUP BY customer_id
                ) latest ON ps.customer_id = latest.customer_id
                        AND ps.timestamp = latest.max_ts
            """)

            snapshots = cursor.fetchall()

            if not snapshots:
                logger.warning(f"No recent snapshots found for cohort")
                return {}

            # Find the customer's own snapshot
            customer_snapshot = None
            for snap in snapshots:
                if snap['customer_id'] == self.customer_id:
                    customer_snapshot = snap
                    break

            if not customer_snapshot:
                logger.warning(f"No recent snapshot found for customer {self.customer_id}")
                return {}

            # Calculate benchmarks for each metric
            metrics_to_benchmark = [
                'health_score',
                'cpu_percent',
                'memory_percent',
                'ttfb_ms',
                'slow_query_count',
                'redis_hit_rate',
            ]

            for metric in metrics_to_benchmark:
                result = self._calculate_metric_benchmark(
                    metric, customer_snapshot, snapshots
                )
                if result:
                    results[metric] = result

        except Exception as e:
            logger.error(f"Error calculating benchmarks for customer {self.customer_id}: {e}")
        finally:
            cursor.close()
            conn.close()

        return results

    def _calculate_metric_benchmark(
        self,
        metric: str,
        customer_snapshot: Dict[str, Any],
        all_snapshots: List[Dict[str, Any]]
    ) -> Optional[BenchmarkResult]:
        """
        Calculate benchmark for a single metric.

        Args:
            metric: The metric name
            customer_snapshot: The customer's latest snapshot
            all_snapshots: All cohort members' snapshots

        Returns:
            BenchmarkResult or None if insufficient data
        """
        customer_value = customer_snapshot.get(metric)
        if customer_value is None:
            return None

        # Convert to float for calculations
        customer_value = float(customer_value)

        # Extract cohort values (excluding None)
        cohort_values = []
        for snap in all_snapshots:
            val = snap.get(metric)
            if val is not None:
                cohort_values.append(float(val))

        if len(cohort_values) < 2:
            # Need at least 2 data points for meaningful comparison
            return None

        # Calculate statistics
        cohort_avg = sum(cohort_values) / len(cohort_values)
        cohort_values_sorted = sorted(cohort_values)

        # Determine best/worst based on metric type
        lower_is_better = metric in LOWER_IS_BETTER_METRICS

        if lower_is_better:
            cohort_best = cohort_values_sorted[0]  # Lowest
            cohort_worst = cohort_values_sorted[-1]  # Highest
        else:
            cohort_best = cohort_values_sorted[-1]  # Highest
            cohort_worst = cohort_values_sorted[0]  # Lowest

        # Calculate percentile
        percentile = self._calculate_percentile(
            customer_value, cohort_values_sorted, lower_is_better
        )

        return BenchmarkResult(
            metric_name=metric,
            customer_value=customer_value,
            cohort_avg=cohort_avg,
            cohort_best=cohort_best,
            cohort_worst=cohort_worst,
            percentile=percentile,
        )

    def _calculate_percentile(
        self,
        value: float,
        sorted_values: List[float],
        lower_is_better: bool
    ) -> int:
        """
        Calculate what percentile the value falls into.

        For lower_is_better metrics, being at the bottom (low values) gives
        a high percentile. For higher_is_better metrics, being at the top
        (high values) gives a high percentile.

        Returns:
            Percentile from 0-100, where 100 is best
        """
        n = len(sorted_values)
        if n == 0:
            return 50  # Default to middle

        # Count how many values the customer beats
        if lower_is_better:
            # Lower is better: count how many have HIGHER (worse) values
            count_worse = sum(1 for v in sorted_values if v > value)
        else:
            # Higher is better: count how many have LOWER (worse) values
            count_worse = sum(1 for v in sorted_values if v < value)

        # Calculate percentile (what percent of the cohort the customer beats)
        percentile = int((count_worse / n) * 100)

        # Clamp to 0-100
        return max(0, min(100, percentile))

    def get_cohort_size(self) -> int:
        """Return number of customers in the cohort."""
        self._ensure_loaded()
        return len(self.cohort_customer_ids)

    def get_cohort_info(self) -> Dict[str, Any]:
        """Get information about the cohort."""
        self._ensure_loaded()

        if not self.customer:
            return {
                'size': 0,
                'platform': None,
                'tier_type': None,
                'description': 'No cohort available',
            }

        platform = self.customer.get('platform', 'unknown')
        tier_type = self.customer.get('tier_type', 'single')
        size = len(self.cohort_customer_ids)

        platform_name = 'WooCommerce' if platform == 'woocommerce' else 'Magento'
        tier_name = 'Multi-Store' if tier_type == 'multi' else 'Single-Store'

        return {
            'size': size,
            'platform': platform,
            'tier_type': tier_type,
            'description': f'{size} {platform_name} {tier_name} stores',
        }


def get_customer_benchmarks(customer_id: int) -> Dict[str, Any]:
    """
    Convenience function to get benchmarks for a customer.

    Args:
        customer_id: The customer ID to benchmark

    Returns:
        Dictionary with:
        - customer_id: The customer ID
        - cohort_size: Number of customers in the cohort
        - cohort_info: Information about the cohort
        - benchmarks: Dict of metric_name -> benchmark details
        - generated_at: ISO timestamp of when benchmarks were generated
    """
    benchmarker = CohortBenchmarker(customer_id)
    benchmarks = benchmarker.get_benchmarks()

    return {
        'customer_id': customer_id,
        'cohort_size': benchmarker.get_cohort_size(),
        'cohort_info': benchmarker.get_cohort_info(),
        'benchmarks': {
            name: result.to_dict() for name, result in benchmarks.items()
        },
        'generated_at': datetime.now().isoformat(),
    }


def get_cohort_summary(customer_id: int) -> Dict[str, Any]:
    """
    Get a simplified benchmark summary suitable for dashboard display.

    Args:
        customer_id: The customer ID

    Returns:
        Dictionary with:
        - overall_percentile: Average percentile across all metrics
        - cohort_size: Number of stores in cohort
        - cohort_description: Human-readable cohort description
        - highlights: List of notable metrics (best/worst performers)
    """
    data = get_customer_benchmarks(customer_id)

    if not data['benchmarks']:
        return {
            'overall_percentile': None,
            'cohort_size': data['cohort_size'],
            'cohort_description': data['cohort_info']['description'],
            'highlights': [],
            'message': 'Insufficient data for benchmarking',
        }

    # Calculate average percentile
    percentiles = [b['percentile'] for b in data['benchmarks'].values()]
    avg_percentile = int(sum(percentiles) / len(percentiles))

    # Find highlights (best and worst performing metrics)
    highlights = []
    sorted_by_percentile = sorted(
        data['benchmarks'].items(),
        key=lambda x: x[1]['percentile'],
        reverse=True
    )

    # Add top performer if excellent
    if sorted_by_percentile:
        best_metric, best_data = sorted_by_percentile[0]
        if best_data['percentile'] >= 80:
            highlights.append({
                'type': 'strength',
                'metric': _format_metric_name(best_metric),
                'percentile': best_data['percentile'],
                'message': f"Top {100 - best_data['percentile']}% for {_format_metric_name(best_metric)}",
            })

    # Add worst performer if below average
    if sorted_by_percentile:
        worst_metric, worst_data = sorted_by_percentile[-1]
        if worst_data['percentile'] < 40:
            highlights.append({
                'type': 'improvement',
                'metric': _format_metric_name(worst_metric),
                'percentile': worst_data['percentile'],
                'message': f"{_format_metric_name(worst_metric)} is below {100 - worst_data['percentile']}% of similar stores",
            })

    return {
        'overall_percentile': avg_percentile,
        'cohort_size': data['cohort_size'],
        'cohort_description': data['cohort_info']['description'],
        'highlights': highlights,
        'rating': _percentile_to_rating(avg_percentile),
    }


def _format_metric_name(metric: str) -> str:
    """Format metric name for display."""
    names = {
        'health_score': 'Health Score',
        'cpu_percent': 'CPU Usage',
        'memory_percent': 'Memory Usage',
        'ttfb_ms': 'Response Time',
        'slow_query_count': 'Database Performance',
        'redis_hit_rate': 'Cache Efficiency',
    }
    return names.get(metric, metric.replace('_', ' ').title())


def _percentile_to_rating(percentile: int) -> str:
    """Convert percentile to rating string."""
    if percentile >= 90:
        return 'excellent'
    elif percentile >= 70:
        return 'good'
    elif percentile >= 40:
        return 'average'
    elif percentile >= 20:
        return 'below_average'
    else:
        return 'poor'
