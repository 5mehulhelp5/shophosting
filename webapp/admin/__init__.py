"""
Admin Panel Blueprint
Provides administrative interface for monitoring the provisioning system
"""

import os
from flask import Blueprint

admin_bp = Blueprint('admin', __name__, template_folder='../templates/admin')

from . import routes
from . import api
from .mail_routes import mail_bp
from .leads_routes import leads_admin_bp

# Register nested blueprints
admin_bp.register_blueprint(mail_bp)
admin_bp.register_blueprint(leads_admin_bp)

# Conditionally register marketing blueprint (gitignored/proprietary)
_marketing_init = os.path.join(os.path.dirname(__file__), 'marketing', '__init__.py')
if os.path.exists(_marketing_init):
    try:
        from .marketing import marketing_bp
        admin_bp.register_blueprint(marketing_bp)
    except ImportError as e:
        import logging
        logging.getLogger(__name__).warning(f"Marketing module not loaded: {e}")
