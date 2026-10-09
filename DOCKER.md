# Running dynamicweb with Docker Compose

Postgres 18, Redis, the web app (Django 6.1, Python 3.12) and a Celery worker in one stack. Only Docker is needed.

## Quick start (VPS or local)

```sh
git clone <this repo> && cd dynamicweb
docker compose up -d --build
docker compose logs -f web      # ready when it prints "Listening at"
```

The first start takes a few minutes (image build, migrations, secret key, sample data).
`docker compose ps` shows "Up" about 1.5 minutes before the site answers, so wait for the log line.
Open port **8000** in the server firewall, then in your browser go to:

- **VPS:** `http://185.203.114.159:8000/dev-sites/`
- **Local machine:** `http://localhost:8000/dev-sites/`

That page lists all 14 sites as links. Each opens as its own site, so you can keep several
open in different tabs. (On a VPS the links look like `http://<domain>.<ip>.sslip.io:8000/`;
sslip.io is public wildcard DNS, so your *browser* needs internet, the server doesn't.)

Admin login: `dummy-admin@example.com` / `dummy-admin` at `/en-us/admin/login/`
(on any site address).

## What you will see

- Every site has sample pages (Home, About, Services, Pricing, Contact) with realistic text.
- ungleich.ch (and blog, comic), datacenterlight.ch and digitalglarus.ch use their own
  design. **The templates of the other 9 sites are not known**, so they show the plain
  Digital Glarus page. That is a test-data limit, not a bug: in production every site's
  pages and template come from the CMS database.
- OpenNebula (VM creation), LDAP accounts and Stripe payments are placeholders and will not
  work (logins use plain Django authentication when no LDAP server is set). Email is printed in the web log.

## Deploying with your own Postgres (production-like)

Create `.env` next to `docker-compose.yml`; values there override `.env.docker`:

```
POSTGRES_HOST=<host>      # PostgreSQL 14 or newer
POSTGRES_PORT=5432
POSTGRES_DB=<db>
POSTGRES_USER=<user>
POSTGRES_PASSWORD=<password>
SEED_DUMMY_DATA=False
DEBUG=False
UNGLEICH_SITE_CONFIGS=<your real JSON>
```

plus your real OpenNebula, LDAP, Stripe, email and reCAPTCHA values. Then:

```sh
docker compose up -d --build --no-deps web celery redis
```

Checklist:

- The database already holds the pages, sites and templates (they are stored in the
  CMS; nothing is created for you). Sample data is skipped anyway when it finds page content.
- `DEBUG=False` loads the production settings and turns off the `/dev-sites/` switcher,
  so reach each site by its real domain name.
- The web container runs gunicorn (static files via WhiteNoise); put a TLS-terminating proxy in
  front. Behind one that sets `X-Forwarded-Proto`, set `BEHIND_TLS_PROXY=True`.

## Image and Kubernetes

One image, `dynamicweb:latest`, serves every role; the `ROLE` variable picks it (compose sets
`ROLE=celery` on the worker):

- `web` (default): migrations, then gunicorn on port 8000
- `celery`: the Celery worker
- `migrate`: run the migrations and exit

Don't override `command:` or `args:` in Kubernetes; `ROLE` is all that is needed.
See [K8S.md](K8S.md) for the Kubernetes deployment.

## Configuration

- `.env.docker`: committed dev defaults. `.env`: your overrides (git-ignored).
- Add a site: add it to `UNGLEICH_SITE_CONFIGS` (a `Site` row is created on start).
- Web server tuning: `GUNICORN_WORKERS` (3), `GUNICORN_TIMEOUT` (120). `RUN_MIGRATIONS=False`
  skips the start-up migrations.
- Sample data off: `SEED_DUMMY_DATA=False`. Remove it later:
  `docker compose exec web python manage.py seed_dummy_data --purge`.
- Restore a real dump: put a `.sql` or `.sql.gz` file in `db-init/`, then
  `docker compose down -v` and start again (dumps are git-ignored).

## Checking that everything works

```sh
docker compose exec web python smoke_test.py
```

Opens all sites, their pages and the admin login, and exits non-zero on any failure.

## Useful commands

```sh
docker compose ps                    # what is running
docker compose logs -f web celery    # logs
docker compose up -d --build         # after code changes (code is baked into the image)
docker compose down                  # stop, keep data (-v wipes it)
```

## Troubleshooting

- **The build fails at `apk add` with "temporary error (try again later)"**, or hangs there:
  the server's DNS is IPv6-only, which containers on Docker's default network cannot use.
  Give Docker IPv4 resolvers and rebuild:

  ```sh
  echo '{"dns": ["1.1.1.1", "9.9.9.9"]}' > /etc/docker/daemon.json   # merge if the file exists
  systemctl restart docker
  docker compose up -d --build
  ```
