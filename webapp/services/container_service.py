"""
Container Service - Manages Docker containers for customer sites

Provides stop/start functionality for customer containers without deleting data.
Used by admin suspend/reactivate actions and automated workers.
"""

import os
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CUSTOMERS_BASE_PATH = Path(os.getenv('CUSTOMERS_BASE_PATH', '/var/customers'))


class ContainerService:
    """Service for managing customer Docker containers"""

    @staticmethod
    def get_customer_dir(customer_id):
        """Get the customer's directory path"""
        return CUSTOMERS_BASE_PATH / f"customer-{customer_id}"

    @staticmethod
    def get_compose_file(customer_id):
        """Get the docker-compose.yml path for a customer"""
        return ContainerService.get_customer_dir(customer_id) / "docker-compose.yml"

    @staticmethod
    def stop_containers(customer_id):
        """
        Stop all containers for a customer (does NOT delete data)

        Args:
            customer_id: The customer ID

        Returns:
            tuple: (success: bool, message: str)
        """
        customer_dir = ContainerService.get_customer_dir(customer_id)
        compose_file = ContainerService.get_compose_file(customer_id)

        if not compose_file.exists():
            logger.warning(f"No docker-compose.yml found for customer {customer_id}")
            return False, "No containers found for this customer"

        try:
            logger.info(f"Stopping containers for customer {customer_id}")
            result = subprocess.run(
                ['docker', 'compose', '-f', str(compose_file), 'stop'],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(customer_dir)
            )

            if result.returncode != 0:
                error_msg = result.stderr or "Unknown error"
                logger.error(f"Failed to stop containers for customer {customer_id}: {error_msg}")
                return False, f"Failed to stop containers: {error_msg}"

            logger.info(f"Containers stopped for customer {customer_id}")
            return True, "Containers stopped successfully"

        except subprocess.TimeoutExpired:
            logger.error(f"Timeout stopping containers for customer {customer_id}")
            return False, "Timeout while stopping containers"
        except Exception as e:
            logger.error(f"Error stopping containers for customer {customer_id}: {e}")
            return False, str(e)

    @staticmethod
    def start_containers(customer_id):
        """
        Start all containers for a customer

        Args:
            customer_id: The customer ID

        Returns:
            tuple: (success: bool, message: str)
        """
        customer_dir = ContainerService.get_customer_dir(customer_id)
        compose_file = ContainerService.get_compose_file(customer_id)

        if not compose_file.exists():
            logger.warning(f"No docker-compose.yml found for customer {customer_id}")
            return False, "No containers found for this customer"

        try:
            logger.info(f"Starting containers for customer {customer_id}")
            result = subprocess.run(
                ['docker', 'compose', '-f', str(compose_file), 'start'],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(customer_dir)
            )

            if result.returncode != 0:
                error_msg = result.stderr or "Unknown error"
                logger.error(f"Failed to start containers for customer {customer_id}: {error_msg}")
                return False, f"Failed to start containers: {error_msg}"

            logger.info(f"Containers started for customer {customer_id}")
            return True, "Containers started successfully"

        except subprocess.TimeoutExpired:
            logger.error(f"Timeout starting containers for customer {customer_id}")
            return False, "Timeout while starting containers"
        except Exception as e:
            logger.error(f"Error starting containers for customer {customer_id}: {e}")
            return False, str(e)

    @staticmethod
    def get_container_status(customer_id):
        """
        Get the status of containers for a customer

        Args:
            customer_id: The customer ID

        Returns:
            dict: Container status info or None if not found
        """
        customer_dir = ContainerService.get_customer_dir(customer_id)
        compose_file = ContainerService.get_compose_file(customer_id)

        if not compose_file.exists():
            return None

        try:
            result = subprocess.run(
                ['docker', 'compose', '-f', str(compose_file), 'ps', '--format', 'json'],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(customer_dir)
            )

            if result.returncode == 0:
                import json
                containers = []
                # docker compose ps --format json outputs one JSON object per line
                for line in result.stdout.strip().split('\n'):
                    if line:
                        try:
                            containers.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass

                running = sum(1 for c in containers if c.get('State') == 'running')
                stopped = sum(1 for c in containers if c.get('State') in ('exited', 'created'))

                return {
                    'total': len(containers),
                    'running': running,
                    'stopped': stopped,
                    'containers': containers
                }

        except Exception as e:
            logger.error(f"Error getting container status for customer {customer_id}: {e}")

        return None

    @staticmethod
    def restart_containers(customer_id):
        """
        Restart all containers for a customer

        Args:
            customer_id: The customer ID

        Returns:
            tuple: (success: bool, message: str)
        """
        customer_dir = ContainerService.get_customer_dir(customer_id)
        compose_file = ContainerService.get_compose_file(customer_id)

        if not compose_file.exists():
            return False, "No containers found for this customer"

        try:
            logger.info(f"Restarting containers for customer {customer_id}")
            result = subprocess.run(
                ['docker', 'compose', '-f', str(compose_file), 'restart'],
                capture_output=True,
                text=True,
                timeout=180,
                cwd=str(customer_dir)
            )

            if result.returncode != 0:
                return False, f"Failed to restart containers: {result.stderr}"

            logger.info(f"Containers restarted for customer {customer_id}")
            return True, "Containers restarted successfully"

        except subprocess.TimeoutExpired:
            return False, "Timeout while restarting containers"
        except Exception as e:
            return False, str(e)
