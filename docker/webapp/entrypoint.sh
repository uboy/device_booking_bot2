#!/bin/sh
set -e

DOMAIN="${DOMAIN:-example.com}"
CONF_HTTP="/etc/nginx/conf.d/webapp-http.conf.template"
CONF_HTTPS="/etc/nginx/conf.d/webapp-https.conf.template"
CONF_OUT="/etc/nginx/conf.d/default.conf"

mkdir -p /var/www/certbot

if [ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ] && [ -f "/etc/letsencrypt/live/${DOMAIN}/privkey.pem" ]; then
  echo "[entrypoint] SSL certs found for ${DOMAIN}, enabling HTTPS"
  envsubst '${DOMAIN}' < "$CONF_HTTPS" > "$CONF_OUT"
else
  echo "[entrypoint] SSL certs not found for ${DOMAIN}, running HTTP-only (ACME webroot ready)"
  envsubst '${DOMAIN}' < "$CONF_HTTP" > "$CONF_OUT"
fi

exec nginx -g 'daemon off;'
