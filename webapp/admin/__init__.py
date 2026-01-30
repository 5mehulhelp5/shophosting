"""
Admin Panel Blueprint
Provides administrative interface for monitoring the provisioning system
"""

from flask import Blueprint

admin_bp = Blueprint('admin', __name__, template_folder='../templates/admin')

from . import routes
from . import api
from .mail_routes import mail_bp

# Register nested blueprints
admin_bp.register_blueprint(mail_bp)
