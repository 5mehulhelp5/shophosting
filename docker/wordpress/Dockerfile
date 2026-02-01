FROM wordpress:latest

# Install mysql client tools (for mysqladmin ping) + curl + unzip (for plugin downloads)
RUN apt-get update \
  && apt-get install -y --no-install-recommends default-mysql-client ca-certificates curl unzip \
  && rm -rf /var/lib/apt/lists/*

# Install WP-CLI
RUN curl -fsSL https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar -o /usr/local/bin/wp \
  && chmod +x /usr/local/bin/wp \
  && wp --info

# Pre-install WordPress to /var/www/html (instead of runtime copy)
# The official WordPress image stores files in /usr/src/wordpress
RUN cp -r /usr/src/wordpress/* /var/www/html/ \
  && chown -R www-data:www-data /var/www/html

# Pre-download WooCommerce and Redis Cache plugins to /usr/src/plugins
# These will be copied to customer volumes on first start
# Download plugins directly from WordPress.org API (avoids wp-cli wp-config requirement)
RUN mkdir -p /usr/src/plugins \
  && cd /usr/src/plugins \
  && curl -sL "https://downloads.wordpress.org/plugin/woocommerce.latest-stable.zip" -o woocommerce.zip \
  && unzip -q woocommerce.zip \
  && rm woocommerce.zip \
  && curl -sL "https://downloads.wordpress.org/plugin/redis-cache.latest-stable.zip" -o redis-cache.zip \
  && unzip -q redis-cache.zip \
  && rm redis-cache.zip \
  && chown -R www-data:www-data /usr/src/plugins

# Add wrapper
COPY entrypoint-wrapper.sh /usr/local/bin/entrypoint-wrapper.sh
RUN chmod +x /usr/local/bin/entrypoint-wrapper.sh

ENTRYPOINT ["/usr/local/bin/entrypoint-wrapper.sh"]
CMD ["apache2-foreground"]
