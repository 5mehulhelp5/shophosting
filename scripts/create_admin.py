#!/usr/bin/env python3
"""
Create Admin User Script
Usage: python3 create_admin.py <email> <password> <full_name> [role]

Roles: super_admin, admin, support (default: admin)
"""

import sys
import os

# Add webapp to path
sys.path.insert(0, '/opt/shophosting/webapp')

from dotenv import load_dotenv
load_dotenv('/opt/shophosting/.env')

from models import init_db_pool
from admin.models import AdminUser


def create_admin(email, password, full_name, role='admin'):
    """Create a new admin user"""
    # Initialize database
    init_db_pool()

    # Check if admin already exists
    existing = AdminUser.get_by_email(email)
    if existing:
        print(f"Error: Admin user with email '{email}' already exists.")
        return False

    # Create new admin
    admin = AdminUser(
        email=email,
        full_name=full_name,
        role=role
    )
    admin.set_password(password)
    admin.save()

    print(f"Admin user created successfully!")
    print(f"  Email: {email}")
    print(f"  Name: {full_name}")
    print(f"  Role: {role}")
    print(f"\nYou can now log in at: /admin/login")

    return True


def main():
    if len(sys.argv) < 4:
        print("Usage: python3 create_admin.py <email> <password> <full_name> [role]")
        print("Roles: super_admin, admin, support (default: admin)")
        print("\nExample:")
        print("  python3 create_admin.py admin@example.com MySecurePass123 'John Admin' super_admin")
        sys.exit(1)

    email = sys.argv[1]
    password = sys.argv[2]
    full_name = sys.argv[3]
    role = sys.argv[4] if len(sys.argv) > 4 else 'admin'

    if role not in ['super_admin', 'admin', 'support']:
        print(f"Error: Invalid role '{role}'. Must be one of: super_admin, admin, support")
        sys.exit(1)

    if len(password) < 8:
        print("Error: Password must be at least 8 characters long.")
        sys.exit(1)

    success = create_admin(email, password, full_name, role)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
