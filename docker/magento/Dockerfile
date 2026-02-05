FROM shinsenter/magento:latest

# Install mysql client tools (for mysqladmin ping) - curl is already installed
# apt-get upgrade pulls in latest security patches for all installed packages
RUN apt-get update \
  && apt-get upgrade -y \
  && apt-get install -y --no-install-recommends default-mysql-client \
  && rm -rf /var/lib/apt/lists/*

# Pre-compile DI and static content for base Magento installation
# This is stored in /usr/src/magento-base for seeding to customer volumes
RUN mkdir -p /usr/src/magento-base \
  && if [ -d /var/www/html/generated ]; then \
       cp -r /var/www/html/generated /usr/src/magento-base/generated; \
     else \
       mkdir -p /usr/src/magento-base/generated; \
     fi \
  && if [ -d /var/www/html/pub/static ]; then \
       cp -r /var/www/html/pub/static /usr/src/magento-base/static; \
     else \
       mkdir -p /usr/src/magento-base/static; \
     fi

# Create marker to indicate base image is ready
RUN touch /usr/src/magento-base/.base-ready

# Add wrapper script
COPY entrypoint-wrapper.sh /usr/local/bin/entrypoint-wrapper.sh
RUN chmod +x /usr/local/bin/entrypoint-wrapper.sh

# Note: Do NOT set USER here - shinsenter/magento requires root to start
# and handles user switching internally via s6-overlay

ENTRYPOINT ["/usr/local/bin/entrypoint-wrapper.sh"]
CMD ["php-fpm"]
