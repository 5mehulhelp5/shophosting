"""
Tests for webapp/leads/battle_scorer.py - Battle Score Calculator
Following TDD: tests written first, implementation follows
"""

import pytest


class TestScoreWeightsConstant:
    """Test SCORE_WEIGHTS constant"""

    def test_score_weights_sum_to_100(self):
        """Test SCORE_WEIGHTS values sum to exactly 100"""
        from leads.battle_scorer import SCORE_WEIGHTS

        total = sum(SCORE_WEIGHTS.values())
        assert total == 100, f"SCORE_WEIGHTS sum to {total}, expected 100"

    def test_score_weights_has_required_keys(self):
        """Test SCORE_WEIGHTS has all required category keys"""
        from leads.battle_scorer import SCORE_WEIGHTS

        required_keys = ['performance', 'mobile', 'tti', 'ttfb', 'security']
        for key in required_keys:
            assert key in SCORE_WEIGHTS, f"Missing key: {key}"

    def test_score_weights_values(self):
        """Test SCORE_WEIGHTS has correct values"""
        from leads.battle_scorer import SCORE_WEIGHTS

        assert SCORE_WEIGHTS['performance'] == 35
        assert SCORE_WEIGHTS['mobile'] == 25
        assert SCORE_WEIGHTS['tti'] == 20
        assert SCORE_WEIGHTS['ttfb'] == 15
        assert SCORE_WEIGHTS['security'] == 5


class TestScoreTiersConstant:
    """Test SCORE_TIERS constant"""

    def test_score_tiers_has_four_tiers(self):
        """Test SCORE_TIERS has exactly 4 tiers"""
        from leads.battle_scorer import SCORE_TIERS

        assert len(SCORE_TIERS) == 4

    def test_score_tiers_structure(self):
        """Test each tier has required keys"""
        from leads.battle_scorer import SCORE_TIERS

        required_keys = ['min', 'label', 'color', 'emoji']
        for tier in SCORE_TIERS:
            for key in required_keys:
                assert key in tier, f"Missing key {key} in tier {tier}"

    def test_score_tiers_order(self):
        """Test tiers are ordered from highest to lowest min"""
        from leads.battle_scorer import SCORE_TIERS

        mins = [tier['min'] for tier in SCORE_TIERS]
        assert mins == sorted(mins, reverse=True), "SCORE_TIERS should be ordered highest to lowest"


class TestNormalizeTti:
    """Test normalize_tti function"""

    def test_normalize_tti_fast_site_1500ms(self):
        """Test normalize_tti returns 100 for 1500ms (fast site)"""
        from leads.battle_scorer import normalize_tti

        score = normalize_tti(1500)
        assert score == 100

    def test_normalize_tti_very_fast_500ms(self):
        """Test normalize_tti returns 100 for 500ms"""
        from leads.battle_scorer import normalize_tti

        score = normalize_tti(500)
        assert score == 100

    def test_normalize_tti_slow_site_10000ms(self):
        """Test normalize_tti returns low score for 10000ms (slow site)"""
        from leads.battle_scorer import normalize_tti

        score = normalize_tti(10000)
        # 10000ms is beyond 8000ms, should be in 20->0 range
        assert score < 20
        assert score >= 0

    def test_normalize_tti_moderate_2500ms(self):
        """Test normalize_tti returns ~90 for 2500ms"""
        from leads.battle_scorer import normalize_tti

        score = normalize_tti(2500)
        assert score == 90

    def test_normalize_tti_moderate_4000ms(self):
        """Test normalize_tti returns 50 for 4000ms"""
        from leads.battle_scorer import normalize_tti

        score = normalize_tti(4000)
        assert score == 50

    def test_normalize_tti_slow_8000ms(self):
        """Test normalize_tti returns 20 for 8000ms"""
        from leads.battle_scorer import normalize_tti

        score = normalize_tti(8000)
        assert score == 20

    def test_normalize_tti_none_returns_50(self):
        """Test normalize_tti returns 50 for None"""
        from leads.battle_scorer import normalize_tti

        score = normalize_tti(None)
        assert score == 50

    def test_normalize_tti_linear_interpolation_2000ms(self):
        """Test normalize_tti linear interpolation in 1500-2500 range"""
        from leads.battle_scorer import normalize_tti

        # At 2000ms, should be halfway between 100 and 90
        score = normalize_tti(2000)
        assert score == 95

    def test_normalize_tti_returns_integer(self):
        """Test normalize_tti returns an integer"""
        from leads.battle_scorer import normalize_tti

        score = normalize_tti(3000)
        assert isinstance(score, int)


class TestNormalizeTtfb:
    """Test normalize_ttfb function"""

    def test_normalize_ttfb_fast_server_100ms(self):
        """Test normalize_ttfb returns 100 for 100ms (fast server)"""
        from leads.battle_scorer import normalize_ttfb

        score = normalize_ttfb(100)
        assert score == 100

    def test_normalize_ttfb_very_fast_50ms(self):
        """Test normalize_ttfb returns 100 for 50ms"""
        from leads.battle_scorer import normalize_ttfb

        score = normalize_ttfb(50)
        assert score == 100

    def test_normalize_ttfb_slow_server_2000ms(self):
        """Test normalize_ttfb returns low score for 2000ms (slow server)"""
        from leads.battle_scorer import normalize_ttfb

        score = normalize_ttfb(2000)
        # 2000ms is boundary, should be 15
        assert score == 15

    def test_normalize_ttfb_very_slow_3000ms(self):
        """Test normalize_ttfb returns very low score for 3000ms"""
        from leads.battle_scorer import normalize_ttfb

        score = normalize_ttfb(3000)
        # Beyond 2000ms, in 15->0 range
        assert score < 15
        assert score >= 0

    def test_normalize_ttfb_moderate_200ms(self):
        """Test normalize_ttfb returns 95 for 200ms"""
        from leads.battle_scorer import normalize_ttfb

        score = normalize_ttfb(200)
        assert score == 95

    def test_normalize_ttfb_moderate_500ms(self):
        """Test normalize_ttfb returns 50 for 500ms"""
        from leads.battle_scorer import normalize_ttfb

        score = normalize_ttfb(500)
        assert score == 50

    def test_normalize_ttfb_slow_1000ms(self):
        """Test normalize_ttfb returns 30 for 1000ms"""
        from leads.battle_scorer import normalize_ttfb

        score = normalize_ttfb(1000)
        assert score == 30

    def test_normalize_ttfb_none_returns_50(self):
        """Test normalize_ttfb returns 50 for None"""
        from leads.battle_scorer import normalize_ttfb

        score = normalize_ttfb(None)
        assert score == 50

    def test_normalize_ttfb_linear_interpolation_150ms(self):
        """Test normalize_ttfb linear interpolation in 100-200 range"""
        from leads.battle_scorer import normalize_ttfb

        # At 150ms, should be halfway between 100 and 95
        score = normalize_ttfb(150)
        assert score == 97 or score == 98  # Allow rounding variance

    def test_normalize_ttfb_returns_integer(self):
        """Test normalize_ttfb returns an integer"""
        from leads.battle_scorer import normalize_ttfb

        score = normalize_ttfb(300)
        assert isinstance(score, int)


class TestGetScoreTier:
    """Test get_score_tier function"""

    def test_get_score_tier_elite_92(self):
        """Test get_score_tier returns Elite tier for score 92"""
        from leads.battle_scorer import get_score_tier

        tier = get_score_tier(92)
        assert tier['label'] == 'Elite'
        assert tier['color'] == 'green'
        assert tier['emoji'] == '🏆'
        assert tier['min'] == 90

    def test_get_score_tier_strong_78(self):
        """Test get_score_tier returns Strong tier for score 78"""
        from leads.battle_scorer import get_score_tier

        tier = get_score_tier(78)
        assert tier['label'] == 'Strong'
        assert tier['color'] == 'blue'
        assert tier['emoji'] == '💪'
        assert tier['min'] == 70

    def test_get_score_tier_needs_work_55(self):
        """Test get_score_tier returns Needs Work tier for score 55"""
        from leads.battle_scorer import get_score_tier

        tier = get_score_tier(55)
        assert tier['label'] == 'Needs Work'
        assert tier['color'] == 'yellow'
        assert tier['emoji'] == '⚠️'
        assert tier['min'] == 50

    def test_get_score_tier_critical_35(self):
        """Test get_score_tier returns Critical tier for score 35"""
        from leads.battle_scorer import get_score_tier

        tier = get_score_tier(35)
        assert tier['label'] == 'Critical'
        assert tier['color'] == 'red'
        assert tier['emoji'] == '🚨'
        assert tier['min'] == 0

    def test_get_score_tier_boundary_90(self):
        """Test get_score_tier returns Elite for exactly 90"""
        from leads.battle_scorer import get_score_tier

        tier = get_score_tier(90)
        assert tier['label'] == 'Elite'

    def test_get_score_tier_boundary_70(self):
        """Test get_score_tier returns Strong for exactly 70"""
        from leads.battle_scorer import get_score_tier

        tier = get_score_tier(70)
        assert tier['label'] == 'Strong'

    def test_get_score_tier_boundary_50(self):
        """Test get_score_tier returns Needs Work for exactly 50"""
        from leads.battle_scorer import get_score_tier

        tier = get_score_tier(50)
        assert tier['label'] == 'Needs Work'

    def test_get_score_tier_zero(self):
        """Test get_score_tier returns Critical for 0"""
        from leads.battle_scorer import get_score_tier

        tier = get_score_tier(0)
        assert tier['label'] == 'Critical'

    def test_get_score_tier_100(self):
        """Test get_score_tier returns Elite for 100"""
        from leads.battle_scorer import get_score_tier

        tier = get_score_tier(100)
        assert tier['label'] == 'Elite'


class TestCalculateBattleScore:
    """Test calculate_battle_score function"""

    def test_calculate_battle_score_perfect_metrics(self):
        """Test calculate_battle_score returns >=95 for perfect metrics"""
        from leads.battle_scorer import calculate_battle_score

        scan_data = {
            'performance_score': 100,
            'pagespeed_data': {
                'lighthouseResult': {
                    'audits': {
                        'interactive': {'numericValue': 1000},  # Fast TTI
                        'server-response-time': {'numericValue': 50}  # Fast TTFB
                    }
                }
            },
            'url': 'https://example.com'  # HTTPS
        }

        score = calculate_battle_score(scan_data)
        assert score >= 95, f"Expected score >= 95 for perfect metrics, got {score}"

    def test_calculate_battle_score_returns_integer(self):
        """Test calculate_battle_score returns an integer 0-100"""
        from leads.battle_scorer import calculate_battle_score

        scan_data = {
            'performance_score': 75,
            'pagespeed_data': {
                'lighthouseResult': {
                    'audits': {
                        'interactive': {'numericValue': 3000},
                        'server-response-time': {'numericValue': 300}
                    }
                }
            },
            'url': 'https://example.com'
        }

        score = calculate_battle_score(scan_data)
        assert isinstance(score, int)
        assert 0 <= score <= 100

    def test_calculate_battle_score_poor_metrics(self):
        """Test calculate_battle_score returns low score for poor metrics"""
        from leads.battle_scorer import calculate_battle_score

        scan_data = {
            'performance_score': 30,
            'pagespeed_data': {
                'lighthouseResult': {
                    'audits': {
                        'interactive': {'numericValue': 10000},  # Slow TTI
                        'server-response-time': {'numericValue': 2500}  # Slow TTFB
                    }
                }
            },
            'url': 'http://example.com'  # No HTTPS
        }

        score = calculate_battle_score(scan_data)
        assert score < 50, f"Expected score < 50 for poor metrics, got {score}"

    def test_calculate_battle_score_uses_ttfb_fallback(self):
        """Test calculate_battle_score uses ttfb_ms fallback when pagespeed_data missing"""
        from leads.battle_scorer import calculate_battle_score

        scan_data = {
            'performance_score': 80,
            'ttfb_ms': 200,
            'url': 'https://example.com'
        }

        score = calculate_battle_score(scan_data)
        assert isinstance(score, int)
        assert 0 <= score <= 100

    def test_calculate_battle_score_https_bonus(self):
        """Test calculate_battle_score gives higher score for HTTPS"""
        from leads.battle_scorer import calculate_battle_score

        base_data = {
            'performance_score': 80,
            'pagespeed_data': {
                'lighthouseResult': {
                    'audits': {
                        'interactive': {'numericValue': 2500},
                        'server-response-time': {'numericValue': 200}
                    }
                }
            }
        }

        https_data = {**base_data, 'url': 'https://example.com'}
        http_data = {**base_data, 'url': 'http://example.com'}

        https_score = calculate_battle_score(https_data)
        http_score = calculate_battle_score(http_data)

        assert https_score > http_score, "HTTPS should give higher score than HTTP"

    def test_calculate_battle_score_mobile_mode(self):
        """Test calculate_battle_score with is_mobile=True"""
        from leads.battle_scorer import calculate_battle_score

        scan_data = {
            'performance_score': 75,
            'pagespeed_data': {
                'lighthouseResult': {
                    'audits': {
                        'interactive': {'numericValue': 3000},
                        'server-response-time': {'numericValue': 300}
                    }
                }
            },
            'url': 'https://example.com'
        }

        # Should work with is_mobile flag
        score = calculate_battle_score(scan_data, is_mobile=True)
        assert isinstance(score, int)
        assert 0 <= score <= 100


class TestGetRoundBreakdown:
    """Test get_round_breakdown function"""

    def test_get_round_breakdown_returns_5_rounds(self):
        """Test get_round_breakdown returns 5 rounds"""
        from leads.battle_scorer import get_round_breakdown

        challenger_data = {
            'performance_score': 85,
            'pagespeed_data': {
                'lighthouseResult': {
                    'audits': {
                        'interactive': {'numericValue': 2000},
                        'server-response-time': {'numericValue': 150}
                    }
                }
            },
            'url': 'https://challenger.com'
        }

        opponent_data = {
            'performance_score': 70,
            'pagespeed_data': {
                'lighthouseResult': {
                    'audits': {
                        'interactive': {'numericValue': 3500},
                        'server-response-time': {'numericValue': 400}
                    }
                }
            },
            'url': 'https://opponent.com'
        }

        rounds = get_round_breakdown(challenger_data, opponent_data)
        assert len(rounds) == 5

    def test_get_round_breakdown_structure(self):
        """Test get_round_breakdown returns rounds with correct structure"""
        from leads.battle_scorer import get_round_breakdown

        challenger_data = {
            'performance_score': 80,
            'pagespeed_data': {
                'lighthouseResult': {
                    'audits': {
                        'interactive': {'numericValue': 2500},
                        'server-response-time': {'numericValue': 200}
                    }
                }
            },
            'url': 'https://challenger.com'
        }

        opponent_data = {
            'performance_score': 75,
            'pagespeed_data': {
                'lighthouseResult': {
                    'audits': {
                        'interactive': {'numericValue': 3000},
                        'server-response-time': {'numericValue': 300}
                    }
                }
            },
            'url': 'https://opponent.com'
        }

        rounds = get_round_breakdown(challenger_data, opponent_data)

        required_keys = ['name', 'key', 'weight', 'challenger_score', 'opponent_score', 'winner', 'margin']
        for round_data in rounds:
            for key in required_keys:
                assert key in round_data, f"Missing key {key} in round {round_data}"

    def test_get_round_breakdown_winner_values(self):
        """Test get_round_breakdown winner is 'challenger', 'opponent', or 'tie'"""
        from leads.battle_scorer import get_round_breakdown

        challenger_data = {
            'performance_score': 80,
            'pagespeed_data': {
                'lighthouseResult': {
                    'audits': {
                        'interactive': {'numericValue': 2500},
                        'server-response-time': {'numericValue': 200}
                    }
                }
            },
            'url': 'https://challenger.com'
        }

        opponent_data = {
            'performance_score': 80,  # Same performance
            'pagespeed_data': {
                'lighthouseResult': {
                    'audits': {
                        'interactive': {'numericValue': 3000},
                        'server-response-time': {'numericValue': 300}
                    }
                }
            },
            'url': 'https://opponent.com'
        }

        rounds = get_round_breakdown(challenger_data, opponent_data)

        for round_data in rounds:
            assert round_data['winner'] in ['challenger', 'opponent', 'tie']

    def test_get_round_breakdown_has_all_categories(self):
        """Test get_round_breakdown includes all scoring categories"""
        from leads.battle_scorer import get_round_breakdown

        challenger_data = {
            'performance_score': 80,
            'pagespeed_data': {
                'lighthouseResult': {
                    'audits': {
                        'interactive': {'numericValue': 2500},
                        'server-response-time': {'numericValue': 200}
                    }
                }
            },
            'url': 'https://challenger.com'
        }

        opponent_data = {
            'performance_score': 75,
            'pagespeed_data': {
                'lighthouseResult': {
                    'audits': {
                        'interactive': {'numericValue': 3000},
                        'server-response-time': {'numericValue': 300}
                    }
                }
            },
            'url': 'https://opponent.com'
        }

        rounds = get_round_breakdown(challenger_data, opponent_data)
        keys = [r['key'] for r in rounds]

        assert 'performance' in keys
        assert 'mobile' in keys
        assert 'tti' in keys
        assert 'ttfb' in keys
        assert 'security' in keys


class TestGetWeakestCategory:
    """Test get_weakest_category function"""

    def test_get_weakest_category_structure(self):
        """Test get_weakest_category returns dict with category, score, weight"""
        from leads.battle_scorer import get_weakest_category

        scan_data = {
            'performance_score': 80,
            'pagespeed_data': {
                'lighthouseResult': {
                    'audits': {
                        'interactive': {'numericValue': 5000},  # Weak TTI
                        'server-response-time': {'numericValue': 200}
                    }
                }
            },
            'url': 'https://example.com'
        }

        result = get_weakest_category(scan_data)

        assert 'category' in result
        assert 'score' in result
        assert 'weight' in result

    def test_get_weakest_category_excludes_security(self):
        """Test get_weakest_category excludes security from consideration"""
        from leads.battle_scorer import get_weakest_category

        # All metrics perfect except security (HTTP instead of HTTPS)
        scan_data = {
            'performance_score': 100,
            'pagespeed_data': {
                'lighthouseResult': {
                    'audits': {
                        'interactive': {'numericValue': 1000},  # Perfect TTI
                        'server-response-time': {'numericValue': 50}  # Perfect TTFB
                    }
                }
            },
            'url': 'http://example.com'  # No HTTPS - but should be excluded
        }

        result = get_weakest_category(scan_data)

        # Security should be excluded, so weakest should be something else
        assert result['category'] != 'security'

    def test_get_weakest_category_identifies_weak_tti(self):
        """Test get_weakest_category correctly identifies weak TTI"""
        from leads.battle_scorer import get_weakest_category

        scan_data = {
            'performance_score': 90,
            'pagespeed_data': {
                'lighthouseResult': {
                    'audits': {
                        'interactive': {'numericValue': 8000},  # Very slow TTI
                        'server-response-time': {'numericValue': 100}  # Fast TTFB
                    }
                }
            },
            'url': 'https://example.com'
        }

        result = get_weakest_category(scan_data)

        # TTI should be the weakest
        assert result['category'] == 'tti'
        assert result['score'] == 20  # normalize_tti(8000) = 20

    def test_get_weakest_category_identifies_weak_ttfb(self):
        """Test get_weakest_category correctly identifies weak TTFB"""
        from leads.battle_scorer import get_weakest_category

        scan_data = {
            'performance_score': 90,
            'pagespeed_data': {
                'lighthouseResult': {
                    'audits': {
                        'interactive': {'numericValue': 1500},  # Fast TTI
                        'server-response-time': {'numericValue': 2000}  # Very slow TTFB
                    }
                }
            },
            'url': 'https://example.com'
        }

        result = get_weakest_category(scan_data)

        # TTFB should be the weakest
        assert result['category'] == 'ttfb'
        assert result['score'] == 15  # normalize_ttfb(2000) = 15
