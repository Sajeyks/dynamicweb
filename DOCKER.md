# Running dynamicweb with Docker Compose

A self-contained test/dev stack: Postgres, Redis, the web app and a Celery worker.
Nothing else needs to be installed on the server.

## Start

```sh
git clone <this repo> && cd dynamicweb
docker compose up -d --build
docker compose logs -f web      # wait for "Starting development server"
```

The first start takes a few minutes: it builds the image, creates the database,
runs all migrations and generates a Django secret key (kept in the `appdata` volume).

The app listens on port **8000**. Open it at `http://<server-ip>:8000/`
(open the port in the server firewall if needed).

## Configuration

- Defaults for everything are in `.env.docker` (committed, dev values only).
- To override a value, create a `.env` file next to `docker-compose.yml`
  (optional, git-ignored). Values there win over `.env.docker`.

### Using your own Postgres instead of the bundled one

Set the connection in `.env`:

```
POSTGRES_HOST=<host>
POSTGRES_PORT=5432
POSTGRES_DB=<db>
POSTGRES_USER=<user>
POSTGRES_PASSWORD=<password>
```

then start everything except the bundled database:

```sh
docker compose up -d --build --no-deps web celery redis
```

## Testing all the sites

The project serves many websites from one app and chooses the site from the
hostname. In this test setup you don't need DNS or `/etc/hosts`: a dev-only
switcher (active when `DEBUG=True`) reads the site from the address, so every site
is its own browser origin and you can open several at once.

- On the machine running the stack, browsers resolve `<domain>.localhost` to
  the local machine, so the links below just work.
- On a remote server, open **`http://<server-ip>:8000/dev-sites/`**: it lists every site as a
  link of the form `http://<domain>.<server-ip>.sslip.io:8000/` (sslip.io is a public wildcard DNS
  service, so the server needs internet access from your browser, not from itself).
- Fallback without wildcard names: `http://<server>:8000/?site=<domain>` remembers the
  site in a cookie (shared by all tabs, so prefer the addresses above).

| Site | Link |
|---|---|
| ungleich.ch | http://ungleich.ch.localhost:8000/ |
| blog.ungleich.ch | http://blog.ungleich.ch.localhost:8000/ |
| comic.ungleich.ch | http://comic.ungleich.ch.localhost:8000/ |
| digitalglarus.ch | http://digitalglarus.ch.localhost:8000/ |
| datacenterlight.ch | http://datacenterlight.ch.localhost:8000/ |
| rails-hosting.ch | http://rails-hosting.ch.localhost:8000/ |
| django-hosting.ch | http://django-hosting.ch.localhost:8000/ |
| node-hosting.ch | http://node-hosting.ch.localhost:8000/ |
| devuanhosting.ch | http://devuanhosting.ch.localhost:8000/ |
| devuanhosting.com | http://devuanhosting.com.localhost:8000/ |
| ipv6onlyhosting.com | http://ipv6onlyhosting.com.localhost:8000/ |
| digitalezukunft.ch | http://digitalezukunft.ch.localhost:8000/ |
| hack4glarus.ch | http://hack4glarus.ch.localhost:8000/ |
| xn--nglarus-n2a.ch | http://xn--nglarus-n2a.ch.localhost:8000/ |

To add a site, add it to
`UNGLEICH_SITE_CONFIGS` in `.env.docker` (a `Site` row is created on start).

## Dummy data

With `SEED_DUMMY_DATA=True` (the default in `.env.docker`), a start on a database
without page content creates sample content that mimics production: per site a home page
in that site's own template with four child pages (About, Services, Pricing, Contact),
plus an admin and 12 customers. The text is written to look like a real site, and only
hidden markers (page `reverse_id` starting with `dummy-`, `dummy-*@example.com` users)
identify it. If the database already has page content (for example the owner's own Postgres)
nothing is added. It is idempotent and only touches what it created.

- Admin login (fixed): `dummy-admin@example.com` / `dummy-admin` at `/en-us/admin/login/`.
  Change the password with `DUMMY_ADMIN_PASSWORD` in `.env` (applies when the admin is first created).
- Turn it off with `SEED_DUMMY_DATA=False` in `.env`.
- Remove it at any time: `docker compose exec web python manage.py seed_dummy_data --purge`.

Real data can also be restored from a plain-SQL `*.sql` / `*.sql.gz` dump in `db-init/`
before the first start. To reload: `docker compose down -v` (deletes volumes) and start
again. Dumps are git-ignored because they contain personal data.

## Useful commands

```sh
docker compose ps                         # what is running
docker compose logs -f web celery         # logs
docker compose up -d --build              # rebuild after code changes (code is baked into the image)
docker compose exec web python manage.py createsuperuser
docker compose down                       # stop (keeps data); add -v to wipe it
```

## Limitations of the test setup

OpenNebula (VM creation), LDAP login and Stripe payments use placeholders and
will not work. Email is printed to the web container log. `DEBUG=True` is on.
