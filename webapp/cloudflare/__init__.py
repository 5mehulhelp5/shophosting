# webapp/cloudflare/__init__.py
"""Cloudflare DNS Management Blueprint"""

from flask import Blueprint

cloudflare_bp = Blueprint('cloudflare', __name__, url_prefix='/dashboard/cloudflare')

# Export API components for use by other modules
from .api import (
    CloudflareAPIError,
    CloudflareAPI
)

# Import routes after blueprint is defined to avoid circular imports
from . import routes

__all__ = [
    'cloudflare_bp',
    'CloudflareAPIError',
    'CloudflareAPI'
]
