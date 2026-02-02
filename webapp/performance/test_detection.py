#!/usr/bin/env python3
"""
Tests for the Issue Detection Rules Engine

Tests cover:
- Detection rule evaluation
- Time-window logic
- Issue creation and storage
- Issue resolution
- Edge cases and error handling
"""

import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, call
from typing import Dict, Any, List

# Add webapp to path for imports
sys.path.insert(0, '/opt/shophosting/webapp')

from performance.detection import (
    IssueDetector,
    DetectedIssue,
    DetectionRule,
    Severity,
    DEFAULT_DETECTION_RULES,
    detect_issues,
    get_detection_rules,
    resolve_issue_by_id,
)


class MockCursor:
    """Mock database cursor for testing"""

    def __init__(self, fetch_results=None):
        self.fetch_results = fetch_results or []
        self.executed_queries = []
        self.executed_params = []
        self.lastrowid = 1

    def execute(self, query, params=None):
        self.executed_queries.append(query)
        self.executed_params.append(params)

    def fetchall(self):
        return self.fetch_results

    def fetchone(self):
        return self.fetch_results[0] if self.fetch_results else None

    def close(self):
        pass


class MockConnection:
    """Mock database connection for testing"""

    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, dictionary=False):
        return self._cursor

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def create_mock_db(snapshots=None, open_issues=None):
    """
    Create a mock database connection function.

    Args:
        snapshots: List of snapshot dicts to return
        open_issues: List of issue dicts to return

    Returns:
        A function that returns a mock connection
    """
    call_count = [0]  # Use list to allow modification in closure

    def mock_get_connection():
        # Return different data based on what query is executed
        cursor = MagicMock()

        def mock_execute(query, params=None):
            cursor.executed_query = query
            cursor.executed_params = params

            if 'performance_snapshots' in query:
                cursor._results = snapshots or []
            elif 'performance_issues' in query and 'SELECT' in query:
                cursor._results = open_issues or []
            else:
                cursor._results = []

        cursor.execute = mock_execute
        cursor.fetchall = lambda: cursor._results
        cursor.fetchone = lambda: cursor._results[0] if cursor._results else None
        cursor.lastrowid = call_count[0] + 1
        cursor.close = lambda: None

        conn = MagicMock()
        conn.cursor = lambda dictionary=False: cursor
        conn.commit = lambda: None
        conn.rollback = lambda: None
        conn.close = lambda: None

        call_count[0] += 1
        return conn

    return mock_get_connection


class TestDetectionRule(unittest.TestCase):
    """Tests for DetectionRule dataclass"""

    def test_rule_creation(self):
        """Test creating a detection rule"""
        rule = DetectionRule(
            issue_type='test_issue',
            metric_name='test_metric',
            threshold=90.0,
            operator='>',
            duration_minutes=5,
            severity=Severity.WARNING,
            description='Test rule'
        )

        self.assertEqual(rule.issue_type, 'test_issue')
        self.assertEqual(rule.metric_name, 'test_metric')
        self.assertEqual(rule.threshold, 90.0)
        self.assertEqual(rule.operator, '>')
        self.assertEqual(rule.duration_minutes, 5)
        self.assertEqual(rule.severity, Severity.WARNING)
        self.assertEqual(rule.description, 'Test rule')

    def test_default_rules_exist(self):
        """Test that all expected default rules are defined"""
        expected_types = [
            'high_memory',
            'critical_memory',
            'high_cpu',
            'slow_queries',
            'cache_miss_storm',
            'disk_filling',
            'disk_critical',
            'response_degradation',
        ]

        rule_types = [rule.issue_type for rule in DEFAULT_DETECTION_RULES]

        for expected in expected_types:
            self.assertIn(expected, rule_types,
                          f"Missing default rule: {expected}")


class TestDetectedIssue(unittest.TestCase):
    """Tests for DetectedIssue dataclass"""

    def test_issue_creation(self):
        """Test creating a detected issue"""
        now = datetime.now()
        issue = DetectedIssue(
            issue_type='high_memory',
            severity=Severity.WARNING,
            detected_at=now,
            details={'current_value': 90.5},
            customer_id=123
        )

        self.assertEqual(issue.issue_type, 'high_memory')
        self.assertEqual(issue.severity, Severity.WARNING)
        self.assertEqual(issue.detected_at, now)
        self.assertEqual(issue.details['current_value'], 90.5)
        self.assertEqual(issue.customer_id, 123)

    def test_to_dict(self):
        """Test converting issue to dictionary"""
        now = datetime.now()
        issue = DetectedIssue(
            issue_type='high_cpu',
            severity=Severity.CRITICAL,
            detected_at=now,
            details={'threshold': 95.0},
            customer_id=456
        )

        result = issue.to_dict()

        self.assertEqual(result['issue_type'], 'high_cpu')
        self.assertEqual(result['severity'], 'critical')
        self.assertEqual(result['detected_at'], now.isoformat())
        self.assertEqual(result['details']['threshold'], 95.0)
        self.assertEqual(result['customer_id'], 456)


class TestIssueDetector(unittest.TestCase):
    """Tests for IssueDetector class"""

    def test_init_with_default_rules(self):
        """Test detector initialization with default rules"""
        detector = IssueDetector(db_connection_func=lambda: None)

        self.assertEqual(len(detector.rules), len(DEFAULT_DETECTION_RULES))
        self.assertIn('high_memory', detector._rules_by_type)
        self.assertIn('critical_memory', detector._rules_by_type)

    def test_init_with_custom_rules(self):
        """Test detector initialization with custom rules"""
        custom_rules = [
            DetectionRule(
                issue_type='custom_issue',
                metric_name='custom_metric',
                threshold=50.0,
                operator='>',
                duration_minutes=1,
                severity=Severity.INFO
            )
        ]

        detector = IssueDetector(
            db_connection_func=lambda: None,
            rules=custom_rules
        )

        self.assertEqual(len(detector.rules), 1)
        self.assertIn('custom_issue', detector._rules_by_type)

    def test_compare_greater_than(self):
        """Test comparison operator: greater than"""
        self.assertTrue(IssueDetector._compare(90, '>', 85))
        self.assertFalse(IssueDetector._compare(80, '>', 85))
        self.assertFalse(IssueDetector._compare(85, '>', 85))

    def test_compare_less_than(self):
        """Test comparison operator: less than"""
        self.assertTrue(IssueDetector._compare(40, '<', 50))
        self.assertFalse(IssueDetector._compare(60, '<', 50))
        self.assertFalse(IssueDetector._compare(50, '<', 50))

    def test_compare_greater_equal(self):
        """Test comparison operator: greater than or equal"""
        self.assertTrue(IssueDetector._compare(90, '>=', 85))
        self.assertTrue(IssueDetector._compare(85, '>=', 85))
        self.assertFalse(IssueDetector._compare(80, '>=', 85))

    def test_compare_less_equal(self):
        """Test comparison operator: less than or equal"""
        self.assertTrue(IssueDetector._compare(40, '<=', 50))
        self.assertTrue(IssueDetector._compare(50, '<=', 50))
        self.assertFalse(IssueDetector._compare(60, '<=', 50))

    def test_compare_invalid_operator(self):
        """Test comparison with invalid operator raises error"""
        with self.assertRaises(ValueError):
            IssueDetector._compare(50, '!=', 50)

    def test_add_rule(self):
        """Test adding a rule dynamically"""
        detector = IssueDetector(
            db_connection_func=lambda: None,
            rules=[]
        )

        new_rule = DetectionRule(
            issue_type='new_rule',
            metric_name='new_metric',
            threshold=75.0,
            operator='>',
            duration_minutes=3,
            severity=Severity.WARNING
        )

        detector.add_rule(new_rule)

        self.assertEqual(len(detector.rules), 1)
        self.assertIn('new_rule', detector._rules_by_type)

    def test_remove_rule(self):
        """Test removing a rule"""
        detector = IssueDetector(db_connection_func=lambda: None)
        initial_count = len(detector.rules)

        result = detector.remove_rule('high_memory')

        self.assertTrue(result)
        self.assertEqual(len(detector.rules), initial_count - 1)
        self.assertNotIn('high_memory', detector._rules_by_type)

    def test_remove_nonexistent_rule(self):
        """Test removing a rule that doesn't exist"""
        detector = IssueDetector(db_connection_func=lambda: None)

        result = detector.remove_rule('nonexistent_rule')

        self.assertFalse(result)

    def test_get_rule(self):
        """Test getting a rule by type"""
        detector = IssueDetector(db_connection_func=lambda: None)

        rule = detector.get_rule('high_memory')

        self.assertIsNotNone(rule)
        self.assertEqual(rule.issue_type, 'high_memory')
        self.assertEqual(rule.threshold, 85.0)

    def test_get_nonexistent_rule(self):
        """Test getting a rule that doesn't exist"""
        detector = IssueDetector(db_connection_func=lambda: None)

        rule = detector.get_rule('nonexistent_rule')

        self.assertIsNone(rule)


class TestTimeWindowDetection(unittest.TestCase):
    """Tests for time-window based detection logic"""

    def test_instant_detection_triggered(self):
        """Test instant detection (duration=0) is triggered"""
        now = datetime.now()
        snapshots = [
            {
                'id': 1,
                'customer_id': 1,
                'timestamp': now,
                'disk_percent': 92.0  # Above 90% threshold
            }
        ]

        mock_db = create_mock_db(snapshots=snapshots, open_issues=[])
        detector = IssueDetector(db_connection_func=mock_db)

        # Use only the disk_filling rule for testing
        detector.rules = [r for r in detector.rules if r.issue_type == 'disk_filling']
        detector._rules_by_type = {r.issue_type: r for r in detector.rules}

        issues = detector.detect_issues(customer_id=1)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, 'disk_filling')
        self.assertEqual(issues[0].severity, Severity.WARNING)

    def test_instant_detection_not_triggered(self):
        """Test instant detection not triggered when below threshold"""
        now = datetime.now()
        snapshots = [
            {
                'id': 1,
                'customer_id': 1,
                'timestamp': now,
                'disk_percent': 85.0  # Below 90% threshold
            }
        ]

        mock_db = create_mock_db(snapshots=snapshots, open_issues=[])
        detector = IssueDetector(db_connection_func=mock_db)

        # Use only the disk_filling rule
        detector.rules = [r for r in detector.rules if r.issue_type == 'disk_filling']
        detector._rules_by_type = {r.issue_type: r for r in detector.rules}

        issues = detector.detect_issues(customer_id=1)

        self.assertEqual(len(issues), 0)

    def test_time_based_detection_sustained(self):
        """Test time-based detection when condition is sustained"""
        now = datetime.now()
        # Create snapshots showing sustained high memory for 5+ minutes
        snapshots = [
            {'id': i, 'customer_id': 1, 'timestamp': now - timedelta(minutes=i),
             'memory_percent': 88.0}
            for i in range(6)  # 6 snapshots, all above 85%
        ]

        mock_db = create_mock_db(snapshots=snapshots, open_issues=[])
        detector = IssueDetector(db_connection_func=mock_db)

        # Use only high_memory rule
        detector.rules = [r for r in detector.rules if r.issue_type == 'high_memory']
        detector._rules_by_type = {r.issue_type: r for r in detector.rules}

        issues = detector.detect_issues(customer_id=1)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, 'high_memory')

    def test_time_based_detection_not_sustained(self):
        """Test time-based detection when condition is not sustained"""
        now = datetime.now()
        # Create snapshots where memory dips below threshold
        snapshots = [
            {'id': 1, 'customer_id': 1, 'timestamp': now, 'memory_percent': 90.0},
            {'id': 2, 'customer_id': 1, 'timestamp': now - timedelta(minutes=1),
             'memory_percent': 80.0},  # Below threshold
            {'id': 3, 'customer_id': 1, 'timestamp': now - timedelta(minutes=2),
             'memory_percent': 88.0},
        ]

        mock_db = create_mock_db(snapshots=snapshots, open_issues=[])
        detector = IssueDetector(db_connection_func=mock_db)

        # Use only high_memory rule
        detector.rules = [r for r in detector.rules if r.issue_type == 'high_memory']
        detector._rules_by_type = {r.issue_type: r for r in detector.rules}

        issues = detector.detect_issues(customer_id=1)

        self.assertEqual(len(issues), 0)

    def test_no_duplicate_issues(self):
        """Test that duplicate issues are not created"""
        now = datetime.now()
        snapshots = [
            {'id': 1, 'customer_id': 1, 'timestamp': now, 'disk_percent': 92.0}
        ]
        open_issues = [
            {'id': 100, 'issue_type': 'disk_filling', 'severity': 'warning',
             'detected_at': now - timedelta(hours=1), 'details': {}}
        ]

        mock_db = create_mock_db(snapshots=snapshots, open_issues=open_issues)
        detector = IssueDetector(db_connection_func=mock_db)

        # Use only disk_filling rule
        detector.rules = [r for r in detector.rules if r.issue_type == 'disk_filling']
        detector._rules_by_type = {r.issue_type: r for r in detector.rules}

        issues = detector.detect_issues(customer_id=1)

        # Should not create duplicate
        self.assertEqual(len(issues), 0)


class TestCacheHitRateDetection(unittest.TestCase):
    """Tests for cache hit rate detection (less-than operator)"""

    def test_cache_miss_storm_triggered(self):
        """Test cache miss storm is detected when hit rate is low"""
        now = datetime.now()
        # Create snapshots showing sustained low cache hit rate
        snapshots = [
            {'id': i, 'customer_id': 1, 'timestamp': now - timedelta(minutes=i),
             'redis_hit_rate': 45.0}  # Below 50% threshold
            for i in range(11)  # 11 snapshots for 10+ minutes
        ]

        mock_db = create_mock_db(snapshots=snapshots, open_issues=[])
        detector = IssueDetector(db_connection_func=mock_db)

        # Use only cache_miss_storm rule
        detector.rules = [r for r in detector.rules if r.issue_type == 'cache_miss_storm']
        detector._rules_by_type = {r.issue_type: r for r in detector.rules}

        issues = detector.detect_issues(customer_id=1)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].issue_type, 'cache_miss_storm')

    def test_cache_hit_rate_normal(self):
        """Test no issue when cache hit rate is normal"""
        now = datetime.now()
        snapshots = [
            {'id': i, 'customer_id': 1, 'timestamp': now - timedelta(minutes=i),
             'redis_hit_rate': 85.0}  # Above 50% threshold
            for i in range(11)
        ]

        mock_db = create_mock_db(snapshots=snapshots, open_issues=[])
        detector = IssueDetector(db_connection_func=mock_db)

        # Use only cache_miss_storm rule
        detector.rules = [r for r in detector.rules if r.issue_type == 'cache_miss_storm']
        detector._rules_by_type = {r.issue_type: r for r in detector.rules}

        issues = detector.detect_issues(customer_id=1)

        self.assertEqual(len(issues), 0)


class TestIssueResolution(unittest.TestCase):
    """Tests for issue resolution logic"""

    def test_issue_resolved_when_condition_clears(self):
        """Test that issues are resolved when conditions improve"""
        now = datetime.now()
        # Current metrics are normal
        snapshots = [
            {'id': 1, 'customer_id': 1, 'timestamp': now, 'disk_percent': 80.0}
        ]
        # But there's an open disk_filling issue
        open_issues = [
            {'id': 100, 'issue_type': 'disk_filling', 'severity': 'warning',
             'detected_at': now - timedelta(hours=1), 'details': {}}
        ]

        # Track if resolve was called
        resolve_called = [False]
        original_resolve = IssueDetector._resolve_issue

        def mock_resolve(self, issue_id, resolved_at):
            resolve_called[0] = True
            # Don't actually call DB

        mock_db = create_mock_db(snapshots=snapshots, open_issues=open_issues)
        detector = IssueDetector(db_connection_func=mock_db)

        # Monkey-patch the resolve method
        detector._resolve_issue = lambda issue_id, resolved_at: mock_resolve(
            detector, issue_id, resolved_at
        )

        # Use only disk_filling rule
        detector.rules = [r for r in detector.rules if r.issue_type == 'disk_filling']
        detector._rules_by_type = {r.issue_type: r for r in detector.rules}

        detector.detect_issues(customer_id=1)

        self.assertTrue(resolve_called[0])


class TestPublicAPI(unittest.TestCase):
    """Tests for public API functions"""

    def test_get_detection_rules(self):
        """Test getting all detection rules"""
        rules = get_detection_rules()

        self.assertIsInstance(rules, list)
        self.assertTrue(len(rules) > 0)

        # Check rule structure
        for rule in rules:
            self.assertIn('issue_type', rule)
            self.assertIn('metric_name', rule)
            self.assertIn('threshold', rule)
            self.assertIn('operator', rule)
            self.assertIn('duration_minutes', rule)
            self.assertIn('severity', rule)
            self.assertIn('description', rule)

    def test_get_detection_rules_contains_expected(self):
        """Test that expected rules are in the list"""
        rules = get_detection_rules()
        rule_types = [r['issue_type'] for r in rules]

        self.assertIn('high_memory', rule_types)
        self.assertIn('critical_memory', rule_types)
        self.assertIn('disk_critical', rule_types)


class TestEdgeCases(unittest.TestCase):
    """Tests for edge cases and error handling"""

    def test_no_snapshots_available(self):
        """Test handling when no snapshots exist"""
        mock_db = create_mock_db(snapshots=[], open_issues=[])
        detector = IssueDetector(db_connection_func=mock_db)

        issues = detector.detect_issues(customer_id=1)

        self.assertEqual(len(issues), 0)

    def test_null_metric_value(self):
        """Test handling of null metric values"""
        now = datetime.now()
        snapshots = [
            {'id': 1, 'customer_id': 1, 'timestamp': now,
             'disk_percent': None}  # Null value
        ]

        mock_db = create_mock_db(snapshots=snapshots, open_issues=[])
        detector = IssueDetector(db_connection_func=mock_db)

        # Use only disk_filling rule
        detector.rules = [r for r in detector.rules if r.issue_type == 'disk_filling']
        detector._rules_by_type = {r.issue_type: r for r in detector.rules}

        issues = detector.detect_issues(customer_id=1)

        self.assertEqual(len(issues), 0)

    def test_insufficient_data_points(self):
        """Test handling when not enough data points for time-based rule"""
        now = datetime.now()
        # Only 1 snapshot for a rule requiring 5 minutes of data
        snapshots = [
            {'id': 1, 'customer_id': 1, 'timestamp': now, 'memory_percent': 90.0}
        ]

        mock_db = create_mock_db(snapshots=snapshots, open_issues=[])
        detector = IssueDetector(db_connection_func=mock_db)

        # Use only high_memory rule (requires 5 min)
        detector.rules = [r for r in detector.rules if r.issue_type == 'high_memory']
        detector._rules_by_type = {r.issue_type: r for r in detector.rules}

        issues = detector.detect_issues(customer_id=1)

        # Should not trigger due to insufficient data
        self.assertEqual(len(issues), 0)

    def test_multiple_issues_same_customer(self):
        """Test detecting multiple issues for the same customer"""
        now = datetime.now()
        snapshots = [
            {'id': 1, 'customer_id': 1, 'timestamp': now,
             'disk_percent': 96.0,  # Triggers both disk_filling and disk_critical
             'memory_percent': 88.0}
        ]

        mock_db = create_mock_db(snapshots=snapshots, open_issues=[])
        detector = IssueDetector(db_connection_func=mock_db)

        # Use disk rules only
        detector.rules = [
            r for r in detector.rules
            if r.issue_type in ('disk_filling', 'disk_critical')
        ]
        detector._rules_by_type = {r.issue_type: r for r in detector.rules}

        issues = detector.detect_issues(customer_id=1)

        # Should detect both disk issues
        self.assertEqual(len(issues), 2)
        issue_types = [i.issue_type for i in issues]
        self.assertIn('disk_filling', issue_types)
        self.assertIn('disk_critical', issue_types)


class TestSeverityLevels(unittest.TestCase):
    """Tests for severity level handling"""

    def test_warning_severity(self):
        """Test warning severity is set correctly"""
        now = datetime.now()
        snapshots = [
            {'id': 1, 'customer_id': 1, 'timestamp': now, 'disk_percent': 92.0}
        ]

        mock_db = create_mock_db(snapshots=snapshots, open_issues=[])
        detector = IssueDetector(db_connection_func=mock_db)

        detector.rules = [r for r in detector.rules if r.issue_type == 'disk_filling']
        detector._rules_by_type = {r.issue_type: r for r in detector.rules}

        issues = detector.detect_issues(customer_id=1)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].severity, Severity.WARNING)

    def test_critical_severity(self):
        """Test critical severity is set correctly"""
        now = datetime.now()
        snapshots = [
            {'id': 1, 'customer_id': 1, 'timestamp': now, 'disk_percent': 96.0}
        ]

        mock_db = create_mock_db(snapshots=snapshots, open_issues=[])
        detector = IssueDetector(db_connection_func=mock_db)

        detector.rules = [r for r in detector.rules if r.issue_type == 'disk_critical']
        detector._rules_by_type = {r.issue_type: r for r in detector.rules}

        issues = detector.detect_issues(customer_id=1)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].severity, Severity.CRITICAL)


def run_tests():
    """Run all tests and return results"""
    print("=" * 70)
    print("Issue Detection Rules Engine - Test Suite")
    print("=" * 70)

    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestDetectionRule))
    suite.addTests(loader.loadTestsFromTestCase(TestDetectedIssue))
    suite.addTests(loader.loadTestsFromTestCase(TestIssueDetector))
    suite.addTests(loader.loadTestsFromTestCase(TestTimeWindowDetection))
    suite.addTests(loader.loadTestsFromTestCase(TestCacheHitRateDetection))
    suite.addTests(loader.loadTestsFromTestCase(TestIssueResolution))
    suite.addTests(loader.loadTestsFromTestCase(TestPublicAPI))
    suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))
    suite.addTests(loader.loadTestsFromTestCase(TestSeverityLevels))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")

    if result.wasSuccessful():
        print("\nAll tests PASSED!")
        return 0
    else:
        print("\nSome tests FAILED!")
        return 1


if __name__ == '__main__':
    sys.exit(run_tests())
