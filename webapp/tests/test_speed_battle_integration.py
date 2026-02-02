"""
Integration tests for Speed Battle feature.
Tests end-to-end flows including battle creation, status polling,
email capture, referral tracking, and share tracking.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime


class TestFullBattleFlow:
    """End-to-end tests for complete battle flow"""

    @patch('rq.Queue')
    @patch('redis.Redis')
    @patch('leads.routes.SpeedBattle')
    def test_full_battle_flow_start_to_completion(self, mock_battle_class, mock_redis, mock_queue, client):
        """
        Test complete battle flow:
        1. Start battle with two URLs
        2. Poll status while pending/scanning
        3. Verify completed state has scores and winner
        """
        # Setup mock battle for creation
        mock_battle = Mock()
        mock_battle.id = 1
        mock_battle.battle_uid = 'flow1234'
        mock_battle.challenger_url = 'https://mystore.com'
        mock_battle.opponent_url = 'https://competitor.com'
        mock_battle.status = 'pending'
        mock_battle_class.create.return_value = mock_battle
        mock_battle_class.get_by_uid.return_value = mock_battle

        mock_queue_instance = Mock()
        mock_queue.return_value = mock_queue_instance

        # Step 1: Start battle
        response = client.post('/speed-battle',
            json={
                'challenger_url': 'https://mystore.com',
                'opponent_url': 'https://competitor.com'
            },
            content_type='application/json')

        assert response.status_code == 200
        data = response.get_json()
        assert data['battle_uid'] == 'flow1234'
        battle_uid = data['battle_uid']

        # Verify job was queued
        mock_queue_instance.enqueue.assert_called_once()

        # Step 2: Poll status - pending
        mock_battle.status = 'pending'
        mock_battle.to_dict.return_value = {
            'battle_uid': battle_uid,
            'status': 'pending',
            'challenger_url': 'https://mystore.com',
            'opponent_url': 'https://competitor.com',
            'challenger_score': None,
            'opponent_score': None,
            'winner': None
        }

        response = client.get(f'/speed-battle/{battle_uid}/status')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'pending'
        assert data['winner'] is None

        # Step 3: Poll status - scanning
        mock_battle.status = 'scanning'
        mock_battle.to_dict.return_value['status'] = 'scanning'

        response = client.get(f'/speed-battle/{battle_uid}/status')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'scanning'

        # Step 4: Poll status - completed with scores
        mock_battle.status = 'completed'
        mock_battle.challenger_score = 85
        mock_battle.opponent_score = 65
        mock_battle.winner = 'challenger'
        mock_battle.margin = 20
        mock_battle.to_dict.return_value = {
            'battle_uid': battle_uid,
            'status': 'completed',
            'challenger_url': 'https://mystore.com',
            'opponent_url': 'https://competitor.com',
            'challenger_score': 85,
            'opponent_score': 65,
            'winner': 'challenger',
            'margin': 20
        }

        response = client.get(f'/speed-battle/{battle_uid}/status')
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'completed'
        assert data['challenger_score'] == 85
        assert data['opponent_score'] == 65
        assert data['winner'] == 'challenger'
        assert data['margin'] == 20

    @patch('rq.Queue')
    @patch('redis.Redis')
    @patch('leads.routes.SpeedBattle')
    def test_battle_flow_opponent_wins(self, mock_battle_class, mock_redis, mock_queue, client):
        """Test battle flow where opponent wins"""
        mock_battle = Mock()
        mock_battle.id = 1
        mock_battle.battle_uid = 'oppwin12'
        mock_battle.challenger_url = 'https://mystore.com'
        mock_battle.opponent_url = 'https://competitor.com'
        mock_battle.status = 'pending'
        mock_battle_class.create.return_value = mock_battle
        mock_battle_class.get_by_uid.return_value = mock_battle

        mock_queue_instance = Mock()
        mock_queue.return_value = mock_queue_instance

        # Start battle
        response = client.post('/speed-battle',
            json={
                'challenger_url': 'https://mystore.com',
                'opponent_url': 'https://competitor.com'
            },
            content_type='application/json')
        assert response.status_code == 200

        # Simulate completion where opponent wins
        mock_battle.status = 'completed'
        mock_battle.challenger_score = 55
        mock_battle.opponent_score = 80
        mock_battle.winner = 'opponent'
        mock_battle.margin = 25
        mock_battle.to_dict.return_value = {
            'battle_uid': 'oppwin12',
            'status': 'completed',
            'challenger_score': 55,
            'opponent_score': 80,
            'winner': 'opponent',
            'margin': 25
        }

        response = client.get('/speed-battle/oppwin12/status')
        data = response.get_json()
        assert data['status'] == 'completed'
        assert data['winner'] == 'opponent'
        assert data['margin'] == 25

    @patch('rq.Queue')
    @patch('redis.Redis')
    @patch('leads.routes.SpeedBattle')
    def test_battle_flow_tie(self, mock_battle_class, mock_redis, mock_queue, client):
        """Test battle flow ending in a tie"""
        mock_battle = Mock()
        mock_battle.id = 1
        mock_battle.battle_uid = 'tie12345'
        mock_battle_class.create.return_value = mock_battle
        mock_battle_class.get_by_uid.return_value = mock_battle

        mock_queue_instance = Mock()
        mock_queue.return_value = mock_queue_instance

        # Start battle
        response = client.post('/speed-battle',
            json={
                'challenger_url': 'https://mystore.com',
                'opponent_url': 'https://competitor.com'
            },
            content_type='application/json')
        assert response.status_code == 200

        # Simulate completion with tie
        mock_battle.status = 'completed'
        mock_battle.challenger_score = 75
        mock_battle.opponent_score = 75
        mock_battle.winner = 'tie'
        mock_battle.margin = 0
        mock_battle.to_dict.return_value = {
            'battle_uid': 'tie12345',
            'status': 'completed',
            'challenger_score': 75,
            'opponent_score': 75,
            'winner': 'tie',
            'margin': 0
        }

        response = client.get('/speed-battle/tie12345/status')
        data = response.get_json()
        assert data['status'] == 'completed'
        assert data['winner'] == 'tie'
        assert data['margin'] == 0

    @patch('leads.routes.SpeedBattle')
    def test_battle_flow_failed_status(self, mock_battle_class, client):
        """Test battle that fails during processing"""
        mock_battle = Mock()
        mock_battle.id = 1
        mock_battle.battle_uid = 'fail1234'
        mock_battle.status = 'failed'
        mock_battle.error_message = 'PageSpeed API error'
        mock_battle.to_dict.return_value = {
            'battle_uid': 'fail1234',
            'status': 'failed',
            'error_message': 'PageSpeed API error',
            'challenger_score': None,
            'opponent_score': None,
            'winner': None
        }
        mock_battle_class.get_by_uid.return_value = mock_battle

        response = client.get('/speed-battle/fail1234/status')
        data = response.get_json()
        assert data['status'] == 'failed'
        assert data['error_message'] == 'PageSpeed API error'


class TestReferralTracking:
    """Tests for referral tracking via ref= parameter"""

    @patch('rq.Queue')
    @patch('redis.Redis')
    @patch('leads.routes.SpeedBattle')
    def test_referral_creates_link_to_referrer(self, mock_battle_class, mock_redis, mock_queue, client):
        """
        Test referral flow:
        1. First user creates a battle
        2. Second user visits with ref= parameter
        3. New battle has referrer_battle_id set
        """
        # Setup original battle (referrer)
        mock_referrer = Mock()
        mock_referrer.id = 10
        mock_referrer.battle_uid = 'orig1234'

        # Setup new battle (referred)
        mock_new_battle = Mock()
        mock_new_battle.id = 20
        mock_new_battle.battle_uid = 'new12345'
        mock_new_battle.referrer_battle_id = 10

        mock_queue_instance = Mock()
        mock_queue.return_value = mock_queue_instance

        # When looking up ref param, return the referrer
        # When creating new battle, return new battle
        mock_battle_class.get_by_uid.return_value = mock_referrer
        mock_battle_class.create.return_value = mock_new_battle

        # Create battle with referral
        response = client.post('/speed-battle?ref=orig1234',
            json={
                'challenger_url': 'https://friend-store.com',
                'opponent_url': 'https://other-store.com'
            },
            content_type='application/json')

        assert response.status_code == 200

        # Verify create was called with referrer_battle_id
        mock_battle_class.create.assert_called_once()
        call_kwargs = mock_battle_class.create.call_args
        # Check that referrer_battle_id=10 was passed
        if call_kwargs.kwargs:
            assert call_kwargs.kwargs.get('referrer_battle_id') == 10
        else:
            # Positional args
            assert 10 in call_kwargs.args or call_kwargs[1].get('referrer_battle_id') == 10

    @patch('rq.Queue')
    @patch('redis.Redis')
    @patch('leads.routes.SpeedBattle')
    def test_invalid_ref_param_no_link(self, mock_battle_class, mock_redis, mock_queue, client):
        """Test that invalid ref param creates battle without referrer link"""
        # No referrer found for the given uid
        mock_battle_class.get_by_uid.return_value = None

        mock_new_battle = Mock()
        mock_new_battle.id = 1
        mock_new_battle.battle_uid = 'new12345'
        mock_battle_class.create.return_value = mock_new_battle

        mock_queue_instance = Mock()
        mock_queue.return_value = mock_queue_instance

        response = client.post('/speed-battle?ref=invalid123',
            json={
                'challenger_url': 'https://mystore.com',
                'opponent_url': 'https://competitor.com'
            },
            content_type='application/json')

        assert response.status_code == 200

        # Verify create was called with referrer_battle_id=None
        mock_battle_class.create.assert_called_once()
        call_kwargs = mock_battle_class.create.call_args
        if call_kwargs.kwargs:
            assert call_kwargs.kwargs.get('referrer_battle_id') is None
        else:
            # Check positional - referrer_battle_id should be None
            assert call_kwargs[1].get('referrer_battle_id') is None

    @patch('leads.routes.SpeedBattle')
    def test_landing_page_with_ref_looks_up_referrer(self, mock_battle_class, client):
        """Test that landing page with ref param looks up the referrer battle"""
        mock_referrer = Mock()
        mock_referrer.battle_uid = 'ref12345'
        mock_referrer.challenger_url = 'https://example.com'
        mock_battle_class.get_by_uid.return_value = mock_referrer

        response = client.get('/speed-battle?ref=ref12345')

        assert response.status_code == 200
        mock_battle_class.get_by_uid.assert_called_once_with('ref12345')

    @patch('leads.routes.SpeedBattle')
    def test_landing_page_without_ref_no_lookup(self, mock_battle_class, client):
        """Test that landing page without ref param doesn't look up referrer"""
        response = client.get('/speed-battle')

        assert response.status_code == 200
        # get_by_uid should not be called if no ref param
        mock_battle_class.get_by_uid.assert_not_called()


class TestEmailSegmentation:
    """Tests for email capture and segmentation based on battle outcome"""

    @patch('rq.Queue')
    @patch('redis.Redis')
    @patch('leads.routes.SpeedBattle')
    def test_email_capture_won_dominant(self, mock_battle_class, mock_redis, mock_queue, client):
        """
        Test email capture when challenger won by 20+ points (dominant)
        Should assign 'won_dominant' segment
        """
        mock_battle = Mock()
        mock_battle.id = 1
        mock_battle.battle_uid = 'dom12345'
        mock_battle.status = 'completed'
        mock_battle.challenger_score = 90
        mock_battle.opponent_score = 60
        mock_battle.winner = 'challenger'
        mock_battle.margin = 30
        mock_battle.get_email_segment.return_value = 'won_dominant'
        mock_battle_class.get_by_uid.return_value = mock_battle

        mock_queue_instance = Mock()
        mock_queue.return_value = mock_queue_instance

        response = client.post('/speed-battle/dom12345/unlock',
            json={'email': 'winner@example.com'},
            content_type='application/json')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['segment'] == 'won_dominant'
        mock_battle.set_email.assert_called_once_with('winner@example.com')

    @patch('rq.Queue')
    @patch('redis.Redis')
    @patch('leads.routes.SpeedBattle')
    def test_email_capture_won_close(self, mock_battle_class, mock_redis, mock_queue, client):
        """
        Test email capture when challenger won by less than 20 points (close)
        Should assign 'won_close' segment
        """
        mock_battle = Mock()
        mock_battle.id = 1
        mock_battle.battle_uid = 'close1234'
        mock_battle.status = 'completed'
        mock_battle.challenger_score = 78
        mock_battle.opponent_score = 70
        mock_battle.winner = 'challenger'
        mock_battle.margin = 8
        mock_battle.get_email_segment.return_value = 'won_close'
        mock_battle_class.get_by_uid.return_value = mock_battle

        mock_queue_instance = Mock()
        mock_queue.return_value = mock_queue_instance

        response = client.post('/speed-battle/close1234/unlock',
            json={'email': 'close-winner@example.com'},
            content_type='application/json')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['segment'] == 'won_close'

    @patch('rq.Queue')
    @patch('redis.Redis')
    @patch('leads.routes.SpeedBattle')
    def test_email_capture_lost_close(self, mock_battle_class, mock_redis, mock_queue, client):
        """
        Test email capture when challenger lost by less than 20 points
        Should assign 'lost_close' segment
        """
        mock_battle = Mock()
        mock_battle.id = 1
        mock_battle.battle_uid = 'lclose12'
        mock_battle.status = 'completed'
        mock_battle.challenger_score = 62
        mock_battle.opponent_score = 75
        mock_battle.winner = 'opponent'
        mock_battle.margin = 13
        mock_battle.get_email_segment.return_value = 'lost_close'
        mock_battle_class.get_by_uid.return_value = mock_battle

        mock_queue_instance = Mock()
        mock_queue.return_value = mock_queue_instance

        response = client.post('/speed-battle/lclose12/unlock',
            json={'email': 'close-loser@example.com'},
            content_type='application/json')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['segment'] == 'lost_close'

    @patch('rq.Queue')
    @patch('redis.Redis')
    @patch('leads.routes.SpeedBattle')
    def test_email_capture_lost_dominant(self, mock_battle_class, mock_redis, mock_queue, client):
        """
        Test email capture when challenger lost by 20+ points
        Should assign 'lost_dominant' segment
        """
        mock_battle = Mock()
        mock_battle.id = 1
        mock_battle.battle_uid = 'ldom1234'
        mock_battle.status = 'completed'
        mock_battle.challenger_score = 45
        mock_battle.opponent_score = 85
        mock_battle.winner = 'opponent'
        mock_battle.margin = 40
        mock_battle.get_email_segment.return_value = 'lost_dominant'
        mock_battle_class.get_by_uid.return_value = mock_battle

        mock_queue_instance = Mock()
        mock_queue.return_value = mock_queue_instance

        response = client.post('/speed-battle/ldom1234/unlock',
            json={'email': 'big-loser@example.com'},
            content_type='application/json')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert data['segment'] == 'lost_dominant'

    @patch('rq.Queue')
    @patch('redis.Redis')
    @patch('leads.routes.SpeedBattle')
    def test_email_capture_queues_email_job(self, mock_battle_class, mock_redis, mock_queue, client):
        """Test that email capture queues send_battle_report_email job"""
        mock_battle = Mock()
        mock_battle.id = 42
        mock_battle.battle_uid = 'email123'
        mock_battle.status = 'completed'
        mock_battle.get_email_segment.return_value = 'won_dominant'
        mock_battle_class.get_by_uid.return_value = mock_battle

        mock_queue_instance = Mock()
        mock_queue.return_value = mock_queue_instance

        response = client.post('/speed-battle/email123/unlock',
            json={'email': 'test@example.com'},
            content_type='application/json')

        assert response.status_code == 200
        # Verify email job was queued
        mock_queue_instance.enqueue.assert_called_once()

    @patch('leads.routes.SpeedBattle')
    def test_email_validation_rejects_invalid(self, mock_battle_class, client):
        """Test that invalid email is rejected"""
        mock_battle = Mock()
        mock_battle.id = 1
        mock_battle.battle_uid = 'val12345'
        mock_battle_class.get_by_uid.return_value = mock_battle

        response = client.post('/speed-battle/val12345/unlock',
            json={'email': 'not-an-email'},
            content_type='application/json')

        assert response.status_code == 400
        data = response.get_json()
        assert 'error' in data


class TestShareTracking:
    """Tests for social share click tracking"""

    @patch('leads.routes.SpeedBattle')
    def test_share_tracking_twitter(self, mock_battle_class, client):
        """Test share click tracking for Twitter"""
        mock_battle = Mock()
        mock_battle.id = 1
        mock_battle.battle_uid = 'share123'
        mock_battle.share_clicks_twitter = 0
        mock_battle_class.get_by_uid.return_value = mock_battle

        response = client.post('/speed-battle/share123/share',
            json={'platform': 'twitter'},
            content_type='application/json')

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        mock_battle.increment_share_click.assert_called_once_with('twitter')

    @patch('leads.routes.SpeedBattle')
    def test_share_tracking_facebook(self, mock_battle_class, client):
        """Test share click tracking for Facebook"""
        mock_battle = Mock()
        mock_battle.id = 1
        mock_battle.battle_uid = 'share123'
        mock_battle_class.get_by_uid.return_value = mock_battle

        response = client.post('/speed-battle/share123/share',
            json={'platform': 'facebook'},
            content_type='application/json')

        assert response.status_code == 200
        mock_battle.increment_share_click.assert_called_once_with('facebook')

    @patch('leads.routes.SpeedBattle')
    def test_share_tracking_linkedin(self, mock_battle_class, client):
        """Test share click tracking for LinkedIn"""
        mock_battle = Mock()
        mock_battle.id = 1
        mock_battle.battle_uid = 'share123'
        mock_battle_class.get_by_uid.return_value = mock_battle

        response = client.post('/speed-battle/share123/share',
            json={'platform': 'linkedin'},
            content_type='application/json')

        assert response.status_code == 200
        mock_battle.increment_share_click.assert_called_once_with('linkedin')

    @patch('leads.routes.SpeedBattle')
    def test_share_tracking_copy_link(self, mock_battle_class, client):
        """Test share click tracking for copy link"""
        mock_battle = Mock()
        mock_battle.id = 1
        mock_battle.battle_uid = 'share123'
        mock_battle_class.get_by_uid.return_value = mock_battle

        response = client.post('/speed-battle/share123/share',
            json={'platform': 'copy'},
            content_type='application/json')

        assert response.status_code == 200
        mock_battle.increment_share_click.assert_called_once_with('copy')

    @patch('leads.routes.SpeedBattle')
    def test_share_tracking_multiple_clicks_same_platform(self, mock_battle_class, client):
        """Test that multiple share clicks increment counter each time"""
        mock_battle = Mock()
        mock_battle.id = 1
        mock_battle.battle_uid = 'multi123'
        mock_battle_class.get_by_uid.return_value = mock_battle

        # Click 3 times on twitter
        for _ in range(3):
            response = client.post('/speed-battle/multi123/share',
                json={'platform': 'twitter'},
                content_type='application/json')
            assert response.status_code == 200

        # increment_share_click should be called 3 times
        assert mock_battle.increment_share_click.call_count == 3

    @patch('leads.routes.SpeedBattle')
    def test_share_tracking_multiple_platforms(self, mock_battle_class, client):
        """Test share tracking across multiple platforms"""
        mock_battle = Mock()
        mock_battle.id = 1
        mock_battle.battle_uid = 'allplat1'
        mock_battle_class.get_by_uid.return_value = mock_battle

        platforms = ['twitter', 'facebook', 'linkedin', 'copy']

        for platform in platforms:
            response = client.post('/speed-battle/allplat1/share',
                json={'platform': platform},
                content_type='application/json')
            assert response.status_code == 200

        # Verify all platforms were tracked
        assert mock_battle.increment_share_click.call_count == 4
        calls = [call[0][0] for call in mock_battle.increment_share_click.call_args_list]
        for platform in platforms:
            assert platform in calls

    @patch('leads.routes.SpeedBattle')
    def test_share_tracking_invalid_platform_rejected(self, mock_battle_class, client):
        """Test that invalid platform is rejected"""
        mock_battle = Mock()
        mock_battle.id = 1
        mock_battle.battle_uid = 'inv12345'
        mock_battle.increment_share_click.side_effect = ValueError("Invalid platform")
        mock_battle_class.get_by_uid.return_value = mock_battle

        response = client.post('/speed-battle/inv12345/share',
            json={'platform': 'tiktok'},
            content_type='application/json')

        assert response.status_code == 400
        data = response.get_json()
        assert 'error' in data

    @patch('leads.routes.SpeedBattle')
    def test_share_tracking_nonexistent_battle_404(self, mock_battle_class, client):
        """Test share tracking returns 404 for nonexistent battle"""
        mock_battle_class.get_by_uid.return_value = None

        response = client.post('/speed-battle/notfound1/share',
            json={'platform': 'twitter'},
            content_type='application/json')

        assert response.status_code == 404


class TestBackgroundJobIntegration:
    """Integration tests for background job processing"""

    def test_run_speed_battle_job_battle_not_found(self):
        """Test run_speed_battle handles missing battle"""
        from leads.jobs import run_speed_battle

        with patch('leads.models.get_db_connection') as mock_get_conn:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = None
            mock_conn = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_get_conn.return_value = mock_conn

            result = run_speed_battle(999)

            assert 'error' in result
            assert result['error'] == 'Battle not found'

    def test_run_speed_battle_job_handles_scan_error(self):
        """Test run_speed_battle handles scan errors gracefully"""
        from leads.jobs import run_speed_battle

        with patch('leads.models.get_db_connection') as mock_get_conn:
            # Setup mock battle from database
            mock_battle_data = {
                'id': 1,
                'battle_uid': 'test1234',
                'challenger_url': 'https://challenger.com',
                'opponent_url': 'https://opponent.com',
                'ip_address': '192.168.1.1',
                'status': 'pending',
                'challenger_scan_id': None,
                'opponent_scan_id': None,
                'challenger_score': None,
                'opponent_score': None,
                'winner': None,
                'margin': None,
                'email': None,
                'email_segment': None,
                'referrer_battle_id': None,
                'share_clicks_twitter': 0,
                'share_clicks_facebook': 0,
                'share_clicks_linkedin': 0,
                'share_clicks_copy': 0,
                'error_message': None,
                'created_at': datetime.now(),
                'updated_at': datetime.now(),
                'completed_at': None
            }
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = mock_battle_data
            mock_conn = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_get_conn.return_value = mock_conn

            with patch('leads.scanner.run_scan') as mock_scan:
                mock_scan.side_effect = Exception("PageSpeed API error")

                result = run_speed_battle(1)

                assert 'error' in result
                assert 'PageSpeed API error' in result['error']


class TestEmailJobIntegration:
    """Integration tests for email sending jobs"""

    def test_send_battle_report_email_no_email(self):
        """Test send_battle_report_email handles missing email"""
        from leads.jobs import send_battle_report_email

        with patch('leads.models.get_db_connection') as mock_get_conn:
            mock_battle_data = {
                'id': 1,
                'battle_uid': 'test1234',
                'challenger_url': 'https://example.com',
                'opponent_url': 'https://other.com',
                'ip_address': '192.168.1.1',
                'status': 'completed',
                'challenger_scan_id': 100,
                'opponent_scan_id': 101,
                'challenger_score': 85,
                'opponent_score': 65,
                'winner': 'challenger',
                'margin': 20,
                'email': None,  # No email set
                'email_segment': None,
                'referrer_battle_id': None,
                'share_clicks_twitter': 0,
                'share_clicks_facebook': 0,
                'share_clicks_linkedin': 0,
                'share_clicks_copy': 0,
                'error_message': None,
                'created_at': datetime.now(),
                'updated_at': datetime.now(),
                'completed_at': datetime.now()
            }
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = mock_battle_data
            mock_conn = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_get_conn.return_value = mock_conn

            result = send_battle_report_email(1)

            assert 'error' in result
            assert result['error'] == 'No email on battle'

    def test_send_battle_report_email_battle_not_found(self):
        """Test send_battle_report_email handles missing battle"""
        from leads.jobs import send_battle_report_email

        with patch('leads.models.get_db_connection') as mock_get_conn:
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = None
            mock_conn = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_get_conn.return_value = mock_conn

            result = send_battle_report_email(999)

            assert 'error' in result
            assert result['error'] == 'Battle not found'

    def test_send_battle_report_email_with_valid_email(self):
        """Test send_battle_report_email sends email correctly"""
        from leads.jobs import send_battle_report_email

        with patch('leads.models.get_db_connection') as mock_get_conn:
            mock_battle_data = {
                'id': 1,
                'battle_uid': 'test1234',
                'challenger_url': 'https://winner.com',
                'opponent_url': 'https://loser.com',
                'ip_address': '192.168.1.1',
                'status': 'completed',
                'challenger_scan_id': 100,
                'opponent_scan_id': 101,
                'challenger_score': 90,
                'opponent_score': 60,
                'winner': 'challenger',
                'margin': 30,
                'email': 'winner@example.com',
                'email_segment': 'won_dominant',
                'referrer_battle_id': None,
                'share_clicks_twitter': 0,
                'share_clicks_facebook': 0,
                'share_clicks_linkedin': 0,
                'share_clicks_copy': 0,
                'error_message': None,
                'created_at': datetime.now(),
                'updated_at': datetime.now(),
                'completed_at': datetime.now()
            }
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = mock_battle_data
            mock_conn = MagicMock()
            mock_conn.cursor.return_value = mock_cursor
            mock_get_conn.return_value = mock_conn

            with patch('email_utils.send_email') as mock_send_email:
                mock_send_email.return_value = (True, 'Sent')

                result = send_battle_report_email(1)

                assert result['success'] is True
                mock_send_email.assert_called_once()
                call_kwargs = mock_send_email.call_args
                assert call_kwargs[1]['to_email'] == 'winner@example.com'


class TestModelEmailSegment:
    """Unit tests for SpeedBattle.get_email_segment method"""

    def test_get_email_segment_challenger_wins_dominant(self):
        """Test segment is won_dominant when challenger wins by 20+"""
        from leads.models import SpeedBattle

        battle = SpeedBattle(
            challenger_score=90,
            opponent_score=65,
            winner='challenger',
            margin=25
        )

        assert battle.get_email_segment() == 'won_dominant'

    def test_get_email_segment_challenger_wins_close(self):
        """Test segment is won_close when challenger wins by <20"""
        from leads.models import SpeedBattle

        battle = SpeedBattle(
            challenger_score=78,
            opponent_score=70,
            winner='challenger',
            margin=8
        )

        assert battle.get_email_segment() == 'won_close'

    def test_get_email_segment_opponent_wins_close(self):
        """Test segment is lost_close when opponent wins by <20"""
        from leads.models import SpeedBattle

        battle = SpeedBattle(
            challenger_score=65,
            opponent_score=78,
            winner='opponent',
            margin=13
        )

        assert battle.get_email_segment() == 'lost_close'

    def test_get_email_segment_opponent_wins_dominant(self):
        """Test segment is lost_dominant when opponent wins by 20+"""
        from leads.models import SpeedBattle

        battle = SpeedBattle(
            challenger_score=50,
            opponent_score=85,
            winner='opponent',
            margin=35
        )

        assert battle.get_email_segment() == 'lost_dominant'

    def test_get_email_segment_exactly_20_is_dominant(self):
        """Test that margin of exactly 20 is considered dominant"""
        from leads.models import SpeedBattle

        battle = SpeedBattle(
            challenger_score=85,
            opponent_score=65,
            winner='challenger',
            margin=20
        )

        assert battle.get_email_segment() == 'won_dominant'

    def test_get_email_segment_19_is_close(self):
        """Test that margin of 19 is considered close"""
        from leads.models import SpeedBattle

        battle = SpeedBattle(
            challenger_score=84,
            opponent_score=65,
            winner='challenger',
            margin=19
        )

        assert battle.get_email_segment() == 'won_close'

    def test_get_email_segment_tie_returns_won_close(self):
        """Test that tie returns won_close (not a loss)"""
        from leads.models import SpeedBattle

        battle = SpeedBattle(
            challenger_score=75,
            opponent_score=75,
            winner='tie',
            margin=0
        )

        segment = battle.get_email_segment()
        # A tie is not a loss, so should be won_close
        assert segment == 'won_close'

    def test_get_email_segment_no_winner_returns_none(self):
        """Test that None is returned when winner not determined"""
        from leads.models import SpeedBattle

        battle = SpeedBattle(
            challenger_score=None,
            opponent_score=None,
            winner=None,
            margin=None
        )

        assert battle.get_email_segment() is None
