#!/bin/sh

set -ue

cd /usr/src/app/

# Persist a generated Django secret key in a shared volume so that every
# container (web, celery) uses the same one across restarts.
if [ -z "${DJANGO_SECRET_KEY:-}" ]; then
    KEY_FILE="${SECRET_KEY_FILE:-/data/secret-key}"
    mkdir -p "$(dirname "$KEY_FILE")"
    if [ ! -s "$KEY_FILE" ]; then
        TMP_KEY="$KEY_FILE.$$"
        python -c 'import random,string;print("".join(random.SystemRandom().choice(string.ascii_letters+string.digits) for _ in range(64)))' > "$TMP_KEY"
        # hard link is atomic: only one container wins the race
        ln "$TMP_KEY" "$KEY_FILE" 2>/dev/null || true
        rm -f "$TMP_KEY"
    fi
    DJANGO_SECRET_KEY="$(cat "$KEY_FILE")"
    export DJANGO_SECRET_KEY
fi

cat > dynamicweb/settings/dynamic.py <<PYEOF
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': '${POSTGRES_DB:-app}',
        'USER': '${POSTGRES_USER:-app}',
        'PASSWORD': '${POSTGRES_PASSWORD:-app}',
        'HOST': '${POSTGRES_HOST:-db}',
        'PORT': '${POSTGRES_PORT:-5432}',
    }
}
PYEOF

# Wait for postgres to accept connections
python - <<'PYEOF'
import os, socket, sys, time
host = os.environ.get('POSTGRES_HOST', 'db')
port = int(os.environ.get('POSTGRES_PORT', 5432))
for _ in range(60):
    try:
        socket.create_connection((host, port), 2).close()
        sys.exit(0)
    except OSError:
        time.sleep(1)
sys.exit("postgres at %s:%s not reachable" % (host, port))
PYEOF

# Explicit arguments win (docker compose run web python manage.py shell);
# otherwise ROLE decides what this container does: web (default), celery, or
# migrate (run the migrations and exit).
if [ "$#" -gt 0 ]; then
    exec "$@"
fi
case "${ROLE:-web}" in
    web)     exec sh start-web.sh ;;
    celery)  exec celery -A dynamicweb worker -l "${CELERY_LOGLEVEL:-info}" ;;
    migrate) MIGRATE_ONLY=True exec sh start-web.sh ;;
    *)       echo "unknown ROLE '$ROLE' (web, celery, migrate)" >&2; exit 1 ;;
esac
