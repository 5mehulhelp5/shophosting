"""
Battle Score Calculator for Speed Battle feature.
Calculates weighted performance scores from scan data.
"""

# Scoring weights for different performance categories (must sum to 100)
SCORE_WEIGHTS = {
    'performance': 35,  # Core Web Vitals / PageSpeed
    'mobile': 25,       # Mobile-specific score
    'tti': 20,          # Time to Interactive
    'ttfb': 15,         # Server response time
    'security': 5       # HTTPS, headers
}

# Score tier definitions (ordered from highest to lowest)
SCORE_TIERS = [
    {'min': 90, 'label': 'Elite', 'color': 'green', 'emoji': '🏆'},
    {'min': 70, 'label': 'Strong', 'color': 'blue', 'emoji': '💪'},
    {'min': 50, 'label': 'Needs Work', 'color': 'yellow', 'emoji': '⚠️'},
    {'min': 0, 'label': 'Critical', 'color': 'red', 'emoji': '🚨'}
]


def normalize_tti(tti_ms):
    """
    Normalize Time to Interactive (TTI) to a 0-100 scale.

    Scoring ranges:
    - <=1500ms: 100
    - 1500-2500ms: 100->90 linear
    - 2500-4000ms: 90->50 linear
    - 4000-8000ms: 50->20 linear
    - >8000ms: 20->0 linear
    - None: 50

    Args:
        tti_ms: Time to Interactive in milliseconds, or None

    Returns:
        int: Normalized score 0-100
    """
    if tti_ms is None:
        return 50

    if tti_ms <= 1500:
        return 100
    elif tti_ms <= 2500:
        # Linear interpolation from 100 to 90
        return int(100 - ((tti_ms - 1500) / 1000) * 10)
    elif tti_ms <= 4000:
        # Linear interpolation from 90 to 50
        return int(90 - ((tti_ms - 2500) / 1500) * 40)
    elif tti_ms <= 8000:
        # Linear interpolation from 50 to 20
        return int(50 - ((tti_ms - 4000) / 4000) * 30)
    else:
        # Linear interpolation from 20 to 0 (for 8000-16000ms range)
        score = int(20 - ((tti_ms - 8000) / 8000) * 20)
        return max(0, score)


def normalize_ttfb(ttfb_ms):
    """
    Normalize Time to First Byte (TTFB) to a 0-100 scale.

    Scoring ranges:
    - <=100ms: 100
    - 100-200ms: 100->95 linear
    - 200-500ms: 95->50 linear
    - 500-1000ms: 50->30 linear
    - 1000-2000ms: 30->15 linear
    - >2000ms: 15->0 linear
    - None: 50

    Args:
        ttfb_ms: Time to First Byte in milliseconds, or None

    Returns:
        int: Normalized score 0-100
    """
    if ttfb_ms is None:
        return 50

    if ttfb_ms <= 100:
        return 100
    elif ttfb_ms <= 200:
        # Linear interpolation from 100 to 95
        return int(100 - ((ttfb_ms - 100) / 100) * 5)
    elif ttfb_ms <= 500:
        # Linear interpolation from 95 to 50
        return int(95 - ((ttfb_ms - 200) / 300) * 45)
    elif ttfb_ms <= 1000:
        # Linear interpolation from 50 to 30
        return int(50 - ((ttfb_ms - 500) / 500) * 20)
    elif ttfb_ms <= 2000:
        # Linear interpolation from 30 to 15
        return int(30 - ((ttfb_ms - 1000) / 1000) * 15)
    else:
        # Linear interpolation from 15 to 0 (for 2000-4000ms range)
        score = int(15 - ((ttfb_ms - 2000) / 2000) * 15)
        return max(0, score)


def get_score_tier(score):
    """
    Get the tier dict based on a score.

    Args:
        score: Integer score 0-100

    Returns:
        dict: Tier dict with min, label, color, emoji
    """
    for tier in SCORE_TIERS:
        if score >= tier['min']:
            return tier
    # Fallback to Critical tier
    return SCORE_TIERS[-1]


def _extract_tti(scan_data):
    """Extract TTI from scan_data pagespeed_data or return None."""
    try:
        return scan_data['pagespeed_data']['lighthouseResult']['audits']['interactive']['numericValue']
    except (KeyError, TypeError):
        return None


def _extract_ttfb(scan_data):
    """Extract TTFB from scan_data pagespeed_data or fallback to ttfb_ms."""
    try:
        return scan_data['pagespeed_data']['lighthouseResult']['audits']['server-response-time']['numericValue']
    except (KeyError, TypeError):
        return scan_data.get('ttfb_ms')


def _get_security_score(url):
    """Get security score based on URL protocol."""
    if url and url.startswith('https://'):
        return 100
    return 0


def _get_category_scores(scan_data, is_mobile=False):
    """
    Extract individual category scores from scan_data.

    Args:
        scan_data: Dict containing performance_score, pagespeed_data, url, etc.
        is_mobile: Whether this is a mobile scan

    Returns:
        dict: Category scores (0-100 for each category)
    """
    performance_score = scan_data.get('performance_score', 50)
    if performance_score is None:
        performance_score = 50

    # For mobile score, use performance_score as base
    # For desktop scans, estimate mobile as slightly lower
    if is_mobile:
        mobile_score = performance_score
    else:
        mobile_score = max(0, performance_score - 10)

    tti_ms = _extract_tti(scan_data)
    ttfb_ms = _extract_ttfb(scan_data)
    url = scan_data.get('url', '')

    return {
        'performance': performance_score,
        'mobile': mobile_score,
        'tti': normalize_tti(tti_ms),
        'ttfb': normalize_ttfb(ttfb_ms),
        'security': _get_security_score(url)
    }


def calculate_battle_score(scan_data, is_mobile=False):
    """
    Calculate weighted battle score from scan data.

    Args:
        scan_data: Dict containing:
            - performance_score: PageSpeed performance score (0-100)
            - pagespeed_data: Nested dict with lighthouse audits
            - ttfb_ms: Fallback TTFB if not in pagespeed_data
            - url: URL for HTTPS check
        is_mobile: Whether this is a mobile scan

    Returns:
        int: Weighted score 0-100
    """
    category_scores = _get_category_scores(scan_data, is_mobile)

    # Calculate weighted sum
    weighted_sum = 0
    for category, weight in SCORE_WEIGHTS.items():
        score = category_scores.get(category, 50)
        weighted_sum += score * weight

    # Divide by 100 (sum of weights) to get final score
    return round(weighted_sum / 100)


def get_round_breakdown(challenger_data, opponent_data):
    """
    Get breakdown of each scoring round/category.

    Args:
        challenger_data: Scan data dict for challenger
        opponent_data: Scan data dict for opponent

    Returns:
        list: List of round dicts with name, key, weight, scores, winner, margin
    """
    challenger_scores = _get_category_scores(challenger_data)
    opponent_scores = _get_category_scores(opponent_data)

    # Define round metadata
    round_metadata = {
        'performance': 'Performance',
        'mobile': 'Mobile Speed',
        'tti': 'Time to Interactive',
        'ttfb': 'Server Response',
        'security': 'Security'
    }

    rounds = []
    for key in ['performance', 'mobile', 'tti', 'ttfb', 'security']:
        challenger_score = challenger_scores[key]
        opponent_score = opponent_scores[key]

        if challenger_score > opponent_score:
            winner = 'challenger'
            margin = challenger_score - opponent_score
        elif opponent_score > challenger_score:
            winner = 'opponent'
            margin = opponent_score - challenger_score
        else:
            winner = 'tie'
            margin = 0

        rounds.append({
            'name': round_metadata[key],
            'key': key,
            'weight': SCORE_WEIGHTS[key],
            'challenger_score': challenger_score,
            'opponent_score': opponent_score,
            'winner': winner,
            'margin': margin
        })

    return rounds


def get_weakest_category(scan_data):
    """
    Get the weakest scoring category (excluding security).

    Args:
        scan_data: Scan data dict

    Returns:
        dict: Dict with category, score, weight for the weakest category
    """
    category_scores = _get_category_scores(scan_data)

    # Find weakest category excluding security
    weakest = None
    weakest_score = 101  # Higher than max possible

    for category, score in category_scores.items():
        if category == 'security':
            continue
        if score < weakest_score:
            weakest_score = score
            weakest = category

    return {
        'category': weakest,
        'score': weakest_score,
        'weight': SCORE_WEIGHTS[weakest]
    }
