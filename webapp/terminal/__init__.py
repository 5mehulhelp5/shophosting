"""
Terminal Blueprint - WP-CLI Terminal for WordPress customers

Provides a restricted shell interface for running WP-CLI commands
and basic shell commands within customer containers.
"""

from flask import Blueprint

terminal_bp = Blueprint('terminal', __name__, url_prefix='/dashboard/terminal')

# Import routes after blueprint creation to avoid circular imports
from . import routes

__all__ = ['terminal_bp']
