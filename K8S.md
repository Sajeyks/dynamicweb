# Running dynamicweb on Kubernetes

One image, `dynamicweb`, runs three roles. Pick the role with the `ROLE` environment variable:

| `ROLE` | What it does |
|---|---|
| `web` (default) | migrations (unless `RUN_MIGRATIONS=False`), then gunicorn on port 8000 |
| `celery` | the Celery worker |
| `migrate` | runs the migrations and exits (for a Job) |

Do not set `command:` or `args:` on the containers. The image's entrypoint writes the database
settings from the environment and waits for Postgres, and `ROLE` does the rest.

> The manifests below follow the image's behaviour but have **not been tested on a cluster**.
> The image itself is tested with `docker compose` (see [DOCKER.md](DOCKER.md)).

## What you need outside the cluster

- **PostgreSQL 18** holding the restored database. The app creates nothing but the schema changes
  from its migrations; pages, sites and templates come from the database.
- **Redis** (cache and Celery broker), in the cluster or outside.

## Configuration

Plain values go in a ConfigMap, passwords and keys in a Secret, both attached with `envFrom`.
The full list is `.env.docker`. The ones that matter:

| Variable | Notes |
|---|---|
| `DEBUG` | `False`. Loads the production settings. |
| `SEED_DUMMY_DATA` | `False`. |
| `DJANGO_SECRET_KEY` | Secret. Required: with several pods nothing else keeps the key the same. |
| `POSTGRES_HOST/PORT/DB/USER/PASSWORD` | the database |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `CACHE_URL` | Redis URLs |
| `UNGLEICH_SITE_CONFIGS` | JSON: host to urlconf, one entry per site |
| `BEHIND_TLS_PROXY` | `True` when TLS ends at the ingress (see below) |
| `OPENNEBULA_*`, `LDAP*`, `STRIPE_*`, `EMAIL_*`, `RECAPTCHA_*`, `WEBHOOK_SECRET` | the real integrations |
| `GUNICORN_WORKERS`, `GUNICORN_TIMEOUT` | default 3 and 120 |
| `RUN_MIGRATIONS` | `False` on the web Deployment when a Job runs the migrations |

## Manifests

```yaml
apiVersion: batch/v1
kind: Job
metadata: {name: dynamicweb-migrate}
spec:
  backoffLimit: 2
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: REGISTRY/dynamicweb:VERSION
          env: [{name: ROLE, value: migrate}]
          envFrom: [{configMapRef: {name: dynamicweb}}, {secretRef: {name: dynamicweb}}]
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: dynamicweb-web}
spec:
  replicas: 2
  selector: {matchLabels: {app: dynamicweb-web}}
  template:
    metadata: {labels: {app: dynamicweb-web}}
    spec:
      containers:
        - name: web
          image: REGISTRY/dynamicweb:VERSION
          env: [{name: RUN_MIGRATIONS, value: "False"}]
          envFrom: [{configMapRef: {name: dynamicweb}}, {secretRef: {name: dynamicweb}}]
          ports: [{containerPort: 8000}]
          readinessProbe: {tcpSocket: {port: 8000}, periodSeconds: 10}
          volumeMounts: [{name: media, mountPath: /usr/src/app/media}]
      volumes:
        - name: media
          persistentVolumeClaim: {claimName: dynamicweb-media}   # ReadWriteMany if replicas > 1
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: dynamicweb-celery}
spec:
  replicas: 1
  selector: {matchLabels: {app: dynamicweb-celery}}
  template:
    metadata: {labels: {app: dynamicweb-celery}}
    spec:
      containers:
        - name: celery
          image: REGISTRY/dynamicweb:VERSION
          env: [{name: ROLE, value: celery}]
          envFrom: [{configMapRef: {name: dynamicweb}}, {secretRef: {name: dynamicweb}}]
---
apiVersion: v1
kind: Service
metadata: {name: dynamicweb-web}
spec:
  selector: {app: dynamicweb-web}
  ports: [{port: 80, targetPort: 8000}]
```

Add an Ingress that sends every site's hostname (all the domains in `UNGLEICH_SITE_CONFIGS`, with
`www.` variants) to the `dynamicweb-web` Service.

## What makes it work well

- **Run the migrations once, as a Job.** Apply the Job and wait for it to finish before rolling out
  the web Deployment. With `RUN_MIGRATIONS=False` the web pods start in seconds and several
  replicas never migrate at the same time.
- **Keep the `Host` header.** The site is chosen from the request's host, so the ingress must pass
  the original host through (the default for most ingress controllers). All hostnames must be in
  `UNGLEICH_SITE_CONFIGS`, in the database's `django_site`/alias tables, and in `ALLOWED_HOSTS`
  (`dynamicweb/settings/prod.py` lists the production domains; add new ones there).
- **TLS at the ingress:** set `BEHIND_TLS_PROXY=True`. Without it Django thinks requests are plain
  http and rejects form posts (admin login, checkout) with a CSRF error. The ingress must set
  `X-Forwarded-Proto`; the common ones do.
- **Static files** are collected when the container starts and served by the app (WhiteNoise); nothing
  to configure.
- **Uploaded media** (the files managed in the admin) is written to `/usr/src/app/media` and served
  by the app. Mount a shared volume there (`ReadWriteMany`), or run one web replica with a normal
  volume. Without a volume, uploads vanish when a pod restarts.
- **Readiness** uses the TCP port: gunicorn only starts listening after start-up work is done. An
  HTTP probe needs a `Host` header that is in `ALLOWED_HOSTS`, which is why it is not used.
- **Logs** go to stdout: `kubectl logs deploy/dynamicweb-web`, `kubectl logs deploy/dynamicweb-celery`.
- **Start-up needs OpenNebula reachable.** The app reads its VM templates at import, once per
  gunicorn worker. If OpenNebula is down the app still starts but logs an error, and VM
  creation is unavailable until a restart.
- **Celery**: keep one replica unless the tasks are known to be safe to run in parallel.

## Checking a deployment

```sh
kubectl logs job/dynamicweb-migrate                  # "No migrations to apply" or the list applied
kubectl rollout status deploy/dynamicweb-web
curl -I -H 'Host: ungleich.ch' http://<ingress-address>/en-us/    # 200
```

The admin is at `/en-us/admin/login/` on any site's address.
