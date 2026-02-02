#!/usr/bin/env python3
"""
Tests for the enhanced metrics collection in monitoring_worker.py
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import sys

# Add paths for imports
sys.path.insert(0, '/opt/shophosting/webapp')
sys.path.insert(0, '/opt/shophosting/provisioning')

from monitoring_worker import (
    PerformanceMetrics,
    MonitoringWorker,
    SLOW_QUERY_THRESHOLD_MS
)


class TestPerformanceMetrics(unittest.TestCase):
    """Test the PerformanceMetrics dataclass"""

    def test_default_values(self):
        """Test that PerformanceMetrics initializes with correct defaults"""
        metrics = PerformanceMetrics(customer_id=1)

        self.assertEqual(metrics.customer_id, 1)
        self.assertIsNone(metrics.ttfb_ms)
        self.assertIsNone(metrics.cpu_percent)
        self.assertIsNone(metrics.memory_percent)
        self.assertIsNone(metrics.slow_query_count)
        self.assertIsNone(metrics.redis_hit_rate)
        self.assertIsNone(metrics.varnish_hit_rate)
        self.assertIsInstance(metrics.timestamp, datetime)

    def test_health_score_perfect(self):
        """Test health score with all good metrics"""
        metrics = PerformanceMetrics(
            customer_id=1,
            ttfb_ms=300,  # < 500ms
            cpu_percent=50,  # < 70%
            memory_percent=60,  # < 75%
            slow_query_count=0,
            redis_hit_rate=95  # > 80%
        )
        score = metrics._calculate_preliminary_health_score()
        self.assertEqual(score, 100)

    def test_health_score_degraded_ttfb(self):
        """Test health score with slow TTFB"""
        metrics = PerformanceMetrics(customer_id=1, ttfb_ms=2000)  # > 1500ms
        score = metrics._calculate_preliminary_health_score()
        self.assertEqual(score, 80)  # 100 - 20

    def test_health_score_critical_cpu(self):
        """Test health score with critical CPU usage"""
        metrics = PerformanceMetrics(customer_id=1, cpu_percent=95)  # > 90%
        score = metrics._calculate_preliminary_health_score()
        self.assertEqual(score, 80)  # 100 - 20

    def test_health_score_low_cache_hit_rate(self):
        """Test health score with low cache hit rate"""
        metrics = PerformanceMetrics(customer_id=1, redis_hit_rate=40)  # < 50%
        score = metrics._calculate_preliminary_health_score()
        self.assertEqual(score, 85)  # 100 - 15

    def test_health_score_multiple_issues(self):
        """Test health score with multiple issues"""
        metrics = PerformanceMetrics(
            customer_id=1,
            ttfb_ms=4000,  # > 3000ms, -30
            cpu_percent=95,  # > 90%, -20
            memory_percent=96,  # > 95%, -20
            slow_query_count=15,  # > 10, -20
            redis_hit_rate=40  # < 50%, -15
        )
        score = metrics._calculate_preliminary_health_score()
        # 100 - 30 - 20 - 20 - 20 - 15 = 0 (capped at 0)
        self.assertEqual(score, 0)

    def test_health_score_no_metrics(self):
        """Test health score when no metrics are available"""
        metrics = PerformanceMetrics(customer_id=1)
        score = metrics._calculate_preliminary_health_score()
        self.assertEqual(score, 100)  # No deductions when no data


class TestMonitoringWorkerMetrics(unittest.TestCase):
    """Test the MonitoringWorker metrics collection methods"""

    def setUp(self):
        self.worker = MonitoringWorker()
        self.mock_customer = Mock()
        self.mock_customer.id = 123
        self.mock_customer.domain = "test.example.com"
        self.mock_customer.platform = "woocommerce"
        self.mock_customer.db_user = "testuser"
        self.mock_customer.db_password = "testpass"
        self.mock_customer.db_name = "testdb"

    @patch('monitoring_worker.subprocess.run')
    def test_container_is_running_true(self, mock_run):
        """Test _container_is_running returns True for running container"""
        mock_run.return_value = Mock(returncode=0, stdout='true\n')
        result = self.worker._container_is_running('customer-123-web')
        self.assertTrue(result)

    @patch('monitoring_worker.subprocess.run')
    def test_container_is_running_false(self, mock_run):
        """Test _container_is_running returns False for non-running container"""
        mock_run.return_value = Mock(returncode=0, stdout='false\n')
        result = self.worker._container_is_running('customer-123-web')
        self.assertFalse(result)

    @patch('monitoring_worker.subprocess.run')
    def test_container_is_running_not_found(self, mock_run):
        """Test _container_is_running returns False when container doesn't exist"""
        mock_run.return_value = Mock(returncode=1, stdout='')
        result = self.worker._container_is_running('customer-123-web')
        self.assertFalse(result)

    @patch.object(MonitoringWorker, '_container_is_running')
    @patch('monitoring_worker.subprocess.run')
    def test_collect_redis_metrics_success(self, mock_run, mock_container_running):
        """Test collecting Redis metrics successfully"""
        mock_container_running.return_value = True

        # Mock Redis INFO stats response
        stats_response = """# Stats
keyspace_hits:1000
keyspace_misses:100
"""
        memory_response = """# Memory
used_memory:1048576
used_memory_human:1M
"""
        mock_run.side_effect = [
            Mock(returncode=0, stdout=stats_response),  # stats call
            Mock(returncode=0, stdout=memory_response),  # memory call
        ]

        result = self.worker.collect_redis_metrics(self.mock_customer, 'customer-123')

        self.assertIsNotNone(result)
        # 1000 / (1000 + 100) * 100 = 90.91%
        self.assertAlmostEqual(result['hit_rate'], 90.91, places=1)
        self.assertEqual(result['memory_bytes'], 1048576)

    @patch.object(MonitoringWorker, '_container_is_running')
    def test_collect_redis_metrics_container_not_running(self, mock_container_running):
        """Test Redis metrics collection when container is not running"""
        mock_container_running.return_value = False

        result = self.worker.collect_redis_metrics(self.mock_customer, 'customer-123')

        self.assertIsNone(result)

    @patch.object(MonitoringWorker, '_container_is_running')
    @patch('monitoring_worker.subprocess.run')
    def test_collect_mysql_metrics_success(self, mock_run, mock_container_running):
        """Test collecting MySQL metrics successfully"""
        mock_container_running.return_value = True

        mock_run.side_effect = [
            Mock(returncode=0, stdout='5\n'),  # slow query count
            Mock(returncode=0, stdout='10\n'),  # active connections
            Mock(returncode=0, stdout='104857600\n'),  # table size (100MB)
        ]

        result = self.worker.collect_mysql_metrics(self.mock_customer, 'customer-123')

        self.assertIsNotNone(result)
        self.assertEqual(result['slow_query_count'], 5)
        self.assertEqual(result['active_connections'], 10)
        self.assertEqual(result['table_size_bytes'], 104857600)

    @patch.object(MonitoringWorker, '_container_is_running')
    def test_collect_mysql_metrics_container_not_running(self, mock_container_running):
        """Test MySQL metrics collection when container is not running"""
        mock_container_running.return_value = False

        result = self.worker.collect_mysql_metrics(self.mock_customer, 'customer-123')

        self.assertIsNone(result)

    @patch.object(MonitoringWorker, '_container_is_running')
    @patch('monitoring_worker.subprocess.run')
    def test_collect_varnish_metrics_success(self, mock_run, mock_container_running):
        """Test collecting Varnish metrics successfully"""
        mock_container_running.return_value = True

        varnish_stats = """MAIN.cache_hit       5000     0.00 Cache hits
MAIN.cache_miss       500     0.00 Cache misses
"""
        mock_run.return_value = Mock(returncode=0, stdout=varnish_stats)

        # Use Magento customer for Varnish
        self.mock_customer.platform = 'magento'

        result = self.worker.collect_varnish_metrics(self.mock_customer, 'customer-123')

        self.assertIsNotNone(result)
        # 5000 / (5000 + 500) * 100 = 90.91%
        self.assertAlmostEqual(result['hit_rate'], 90.91, places=1)

    @patch.object(MonitoringWorker, '_container_is_running')
    def test_collect_varnish_metrics_container_not_running(self, mock_container_running):
        """Test Varnish metrics collection when container is not running"""
        mock_container_running.return_value = False
        self.mock_customer.platform = 'magento'

        result = self.worker.collect_varnish_metrics(self.mock_customer, 'customer-123')

        self.assertIsNone(result)


class TestHttpWithTTFB(unittest.TestCase):
    """Test the enhanced HTTP check with TTFB measurement"""

    def setUp(self):
        self.worker = MonitoringWorker()
        self.mock_customer = Mock()
        self.mock_customer.domain = "test.example.com"

    @patch('monitoring_worker.requests.get')
    def test_check_http_with_ttfb_success(self, mock_get):
        """Test successful HTTP check with TTFB"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'<html></html>'
        mock_get.return_value = mock_response

        success, response_time, ttfb = self.worker.check_http_with_ttfb(self.mock_customer)

        self.assertTrue(success)
        self.assertIsNotNone(response_time)
        self.assertIsNotNone(ttfb)
        self.assertGreaterEqual(response_time, ttfb)

    @patch('monitoring_worker.requests.get')
    def test_check_http_with_ttfb_server_error(self, mock_get):
        """Test HTTP check with server error"""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.content = b'Error'
        mock_get.return_value = mock_response

        success, response_time, ttfb = self.worker.check_http_with_ttfb(self.mock_customer)

        self.assertFalse(success)
        self.assertIsNotNone(response_time)
        self.assertIsNotNone(ttfb)

    @patch('monitoring_worker.requests.get')
    def test_check_http_with_ttfb_timeout(self, mock_get):
        """Test HTTP check timeout"""
        import requests
        mock_get.side_effect = requests.exceptions.Timeout()

        success, response_time, ttfb = self.worker.check_http_with_ttfb(self.mock_customer)

        self.assertFalse(success)
        self.assertIsNone(response_time)
        self.assertIsNone(ttfb)

    @patch('monitoring_worker.requests.get')
    def test_check_http_legacy_compatibility(self, mock_get):
        """Test that legacy check_http method still works"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.content = b'<html></html>'
        mock_get.return_value = mock_response

        success, response_time = self.worker.check_http(self.mock_customer)

        self.assertTrue(success)
        self.assertIsNotNone(response_time)


class TestCollectPerformanceMetrics(unittest.TestCase):
    """Test the complete performance metrics collection flow"""

    def setUp(self):
        self.worker = MonitoringWorker()
        self.mock_customer = Mock()
        self.mock_customer.id = 123
        self.mock_customer.domain = "test.example.com"
        self.mock_customer.platform = "woocommerce"
        self.mock_customer.db_user = "testuser"
        self.mock_customer.db_password = "testpass"
        self.mock_customer.db_name = "testdb"

    @patch.object(PerformanceMetrics, 'save')
    @patch.object(MonitoringWorker, 'collect_varnish_metrics')
    @patch.object(MonitoringWorker, 'collect_redis_metrics')
    @patch.object(MonitoringWorker, 'collect_mysql_metrics')
    def test_collect_performance_metrics_woocommerce(
            self, mock_mysql, mock_redis, mock_varnish, mock_save):
        """Test metrics collection for WooCommerce (no Varnish)"""
        mock_mysql.return_value = {
            'slow_query_count': 2,
            'active_connections': 5,
            'table_size_bytes': 1000000
        }
        mock_redis.return_value = {'hit_rate': 85.5, 'memory_bytes': 5000000}

        self.worker.collect_performance_metrics(
            self.mock_customer,
            ttfb_ms=250,
            cpu_percent=45.0,
            mem_percent=60.0
        )

        # Varnish should not be collected for WooCommerce
        mock_varnish.assert_not_called()
        mock_save.assert_called_once()

    @patch.object(PerformanceMetrics, 'save')
    @patch.object(MonitoringWorker, 'collect_varnish_metrics')
    @patch.object(MonitoringWorker, 'collect_redis_metrics')
    @patch.object(MonitoringWorker, 'collect_mysql_metrics')
    def test_collect_performance_metrics_magento(
            self, mock_mysql, mock_redis, mock_varnish, mock_save):
        """Test metrics collection for Magento (with Varnish)"""
        self.mock_customer.platform = "magento"

        mock_mysql.return_value = {'slow_query_count': 0}
        mock_redis.return_value = {'hit_rate': 90.0}
        mock_varnish.return_value = {'hit_rate': 95.0}

        self.worker.collect_performance_metrics(
            self.mock_customer,
            ttfb_ms=150,
            cpu_percent=30.0,
            mem_percent=50.0
        )

        # Varnish should be collected for Magento
        mock_varnish.assert_called_once()
        mock_save.assert_called_once()

    @patch.object(PerformanceMetrics, 'save')
    @patch.object(MonitoringWorker, 'collect_redis_metrics')
    @patch.object(MonitoringWorker, 'collect_mysql_metrics')
    def test_collect_performance_metrics_handles_missing_containers(
            self, mock_mysql, mock_redis, mock_save):
        """Test that missing containers are handled gracefully"""
        mock_mysql.return_value = None  # MySQL container not running
        mock_redis.return_value = None  # Redis container not running

        # Should not raise an exception
        self.worker.collect_performance_metrics(
            self.mock_customer,
            ttfb_ms=300,
            cpu_percent=50.0,
            mem_percent=60.0
        )

        mock_save.assert_called_once()


if __name__ == '__main__':
    unittest.main()
