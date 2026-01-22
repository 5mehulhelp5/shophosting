FROM shinsenter/magento:latest

# Install mysql client tools (for mysqladmin ping) - curl is already installed
RUN apt-get update \
  && apt-get install -y --no-install-recommends default-mysql-client \
  && rm -rf /var/lib/apt/lists/*

# Add wrapper script
COPY entrypoint-wrapper.sh /usr/local/bin/entrypoint-wrapper.sh
RUN chmod +x /usr/local/bin/entrypoint-wrapper.sh

# Note: Do NOT set USER here - shinsenter/magento requires root to start
# and handles user switching internally via s6-overlay

ENTRYPOINT ["/usr/local/bin/entrypoint-wrapper.sh"]
CMD ["php-fpm"]
