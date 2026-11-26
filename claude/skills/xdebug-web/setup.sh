#!/usr/bin/env bash
# Arms on-trigger Xdebug tracing on every local FPM pool (system php-fpm + remi SCL php8x-php-fpm).
# Idempotent. Run with sudo.
set -euo pipefail
OUT=/var/lib/xdebug
OWNER=${SUDO_USER:-user}
INI="$(cd "$(dirname "$0")" && pwd)/xdebug-trace.ini"

# SCL pools run as $OWNER, system pool as apache -> group-writable, setgid.
install -d -o "$OWNER" -g apache -m 2775 "$OUT"
if command -v semanage >/dev/null; then
    semanage fcontext -a -t httpd_sys_rw_content_t "$OUT(/.*)?" 2>/dev/null \
        || semanage fcontext -m -t httpd_sys_rw_content_t "$OUT(/.*)?"
    restorecon -R "$OUT"
else
    # ponytail: chcon is not persistent across relabel; dnf install policycoreutils-python-utils for semanage
    chcon -R -t httpd_sys_rw_content_t "$OUT"
fi

for d in /etc/php.d /etc/opt/remi/php*/php.d; do
    [ -f "$d/15-xdebug.ini" ] || continue
    install -m 644 "$INI" "$d/16-xdebug-trace.ini"
    echo "installed $d/16-xdebug-trace.ini"
done

for u in php-fpm php81-php-fpm php82-php-fpm php83-php-fpm php84-php-fpm; do
    systemctl is-active -q "$u" 2>/dev/null && systemctl reload "$u" && echo "reloaded $u" || true
done
