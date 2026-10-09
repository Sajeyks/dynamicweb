# Deploying dynamicweb on Kubernetes

The Helm chart in [charts/dynamicweb/](charts/dynamicweb/) runs the web app, a Celery worker,
Redis, a volume for uploaded media and an Ingress, and runs the database migrations as a Job
before each install or upgrade. PostgreSQL 18 is **not** in the chart: bring your own (an
operator such as CloudNativePG, a managed service, or any Postgres) and point the app at it.

> Tested on a local `kind` cluster with a scratch Postgres. Not tested on your cluster, your
> ingress controller or real data.

## Steps

1. **Push the image** (built once from the repo):
   ```sh
   docker compose build
   docker tag dynamicweb:latest <registry>/dynamicweb:<version>
   docker push <registry>/dynamicweb:<version>
   ```
2. **Database.** Create an empty database and user. To keep old data, restore the dump into it now
   (`psql -h <host> -U <user> <db> < dump.sql`). The Job in step 5 migrates it to the new schema.
3. **Env file and Secret.** Copy `.env.docker`, set your real values, then store it:
   ```
   DEBUG=False
   SEED_DUMMY_DATA=False
   DJANGO_SECRET_KEY=<a long random string>
   POSTGRES_HOST=<host>   POSTGRES_PORT=5432   POSTGRES_DB / POSTGRES_USER / POSTGRES_PASSWORD
   BEHIND_TLS_PROXY=True                   # TLS ends at the ingress
   UNGLEICH_SITE_CONFIGS=<your real JSON>
   ```
   plus your OpenNebula, LDAP, Stripe, email and reCAPTCHA values. Leave the Redis URLs alone.
   ```sh
   kubectl create secret generic dynamicweb --from-env-file=<your env file>
   ```
4. **Values.** Edit `image.repository`, `image.tag` and `ingress.hosts` (one per domain, with `www.`
   variants) in [charts/dynamicweb/values.yaml](charts/dynamicweb/values.yaml), or pass them with `--set`.
5. **Install.** Helm starts the pods and runs the migrate Job (on upgrades, before the rollout). The site answers once the Job completes:
   ```sh
   helm install dynamicweb charts/dynamicweb
   kubectl logs -f job/dynamicweb-migrate        # a few minutes
   kubectl logs -f deploy/dynamicweb-web         # ready at "Listening at"
   ```
6. **Check:** `curl -I -H 'Host: ungleich.ch' http://<ingress-address>/en-us/` returns 200. Admin is
   at `/en-us/admin/login/` on any site's address.

## Good to know

- **Update:** push a new tag, then `helm upgrade dynamicweb charts/dynamicweb --set image.tag=<new>`.
  The migrate Job runs again first.
- **Scale web:** `--set web.replicas=2 --set media.accessMode=ReadWriteMany` (every pod must see the
  same uploads, so the storage class has to support it).
- **Keep the original `Host` header** at the ingress (the default). The site is chosen from the host,
  and every domain must be in `UNGLEICH_SITE_CONFIGS` and `ALLOWED_HOSTS` (`dynamicweb/settings/prod.py`).
- **The Secret must exist before `helm install`** (the Job reads it).
- **Logs:** `kubectl logs deploy/dynamicweb-web`, `deploy/dynamicweb-celery`.
- **Why a database Service named `postgres` is safe:** the pods set `enableServiceLinks: false`;
  otherwise Kubernetes injects `POSTGRES_PORT=tcp://...` and the app crashes.
