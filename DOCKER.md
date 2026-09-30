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
switcher picks the site from `?site=<domain>` and remembers it in a cookie.

Open **`/dev-sites/`** on any host for a page of clickable links
(`http://<server-ip>:8000/dev-sites/`). On a machine running the stack locally:

| Site | Link |
|---|---|
| ungleich.ch | http://localhost:8000/?site=ungleich.ch |
| blog.ungleich.ch | http://localhost:8000/?site=blog.ungleich.ch |
| comic.ungleich.ch | http://localhost:8000/?site=comic.ungleich.ch |
| digitalglarus.ch | http://localhost:8000/?site=digitalglarus.ch |
| datacenterlight.ch | http://localhost:8000/?site=datacenterlight.ch |
| rails-hosting.ch | http://localhost:8000/?site=rails-hosting.ch |
| django-hosting.ch | http://localhost:8000/?site=django-hosting.ch |
| node-hosting.ch | http://localhost:8000/?site=node-hosting.ch |
| devuanhosting.ch | http://localhost:8000/?site=devuanhosting.ch |
| devuanhosting.com | http://localhost:8000/?site=devuanhosting.com |
| ipv6onlyhosting.com | http://localhost:8000/?site=ipv6onlyhosting.com |
| digitalezukunft.ch | http://localhost:8000/?site=digitalezukunft.ch |
| hack4glarus.ch | http://localhost:8000/?site=hack4glarus.ch |
| xn--nglarus-n2a.ch | http://localhost:8000/?site=xn--nglarus-n2a.ch |

Use `?site=` (empty) to clear the choice. To add a site, add it to
`UNGLEICH_SITE_CONFIGS` in `.env.docker` (a `Site` row is created on start).

## Loading data (optional)

The database starts empty, so the sites are mostly blank. To load a dump, put a
plain-SQL `*.sql` or `*.sql.gz` file in `db-init/` **before the first start**; Postgres
restores it automatically. To reload: `docker compose down -v` (this deletes the
volumes) and start again. Dumps are git-ignored because they contain personal data.

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
