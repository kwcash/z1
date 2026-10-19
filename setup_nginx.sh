#!/usr/bin/env bash
# Put nginx + free HTTPS (Let's Encrypt) in front of the private API.
#   cd /root/z1 && DOMAIN=api.example.com EMAIL=you@example.com bash setup_nginx.sh
#
# Before running:
#   1. DNS: an A record for $DOMAIN pointing at this VPS's IP (check: dig +short $DOMAIN)
#   2. At least one API key:  bash keys.sh add <name>
# The API itself keeps listening on 127.0.0.1:8000; only nginx faces the internet.
set -euo pipefail

cd /root/z1
: "${DOMAIN:?set DOMAIN=your.domain.name}"
: "${EMAIL:?set EMAIL=you@example.com (certificate expiry notices go here)}"
[ -s api_keys.txt ] || { echo "No API key yet. Run: bash keys.sh add <name>   (never expose the API without one)"; exit 1; }

echo "== 1/4 install nginx and certbot"
apt-get update -qq
apt-get install -y -qq nginx certbot python3-certbot-nginx

echo "== 2/4 nginx site for $DOMAIN"
cat > /etc/nginx/sites-available/z1-api <<EOF
limit_req_zone \$binary_remote_addr zone=z1api:10m rate=10r/s;

server {
    listen 80;
    server_name $DOMAIN;

    location / {
        limit_req zone=z1api burst=20 nodelay;
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 30s;
    }
}
EOF
ln -sf /etc/nginx/sites-available/z1-api /etc/nginx/sites-enabled/z1-api
nginx -t
systemctl reload nginx

echo "== 3/4 firewall"
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    ufw allow 'Nginx Full' >/dev/null
    echo "ufw: allowed 80/443"
else
    echo "ufw not active; make sure ports 80 and 443 are open at your provider's firewall too"
fi

echo "== 4/4 HTTPS certificate (redirects http -> https)"
certbot --nginx -d "$DOMAIN" -m "$EMAIL" --agree-tos --no-eff-email --redirect -n

echo "== check"
curl -fsS "https://$DOMAIN/api/health"; echo
printf 'no key  -> %s (expect 401)\n' "$(curl -s -o /dev/null -w '%{http_code}' "https://$DOMAIN/api/tables")"
echo "Done. Call it with:  curl -H 'X-API-Key: <key>' https://$DOMAIN/api/sector/15"
echo "Interactive docs:    https://$DOMAIN/docs   (use Authorize with your key)"
