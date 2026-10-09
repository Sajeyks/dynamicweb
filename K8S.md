# Deploying dynamicweb on Kubernetes

[k8s/dynamicweb.yaml](k8s/dynamicweb.yaml) describes what runs: the web app, the Celery worker,
Redis, a volume for uploaded media, and an Ingress. PostgreSQL 18 is **not** included: use your
own database and point the app at it.

> Tested on a local `kind` cluster with a scratch Postgres (migrate Job, then web and the admin
> answer 200). Not tested on your cluster, ingress controller or real data.

## Steps

1. **Push the image** (build it once, from the repo):
   ```sh
   docker compose build
   docker tag dynamicweb:latest <registry>/dynamicweb:<version>
   docker push <registry>/dynamicweb:<version>
   ```
2. **Make an env file** from `.env.docker` with your real values. Change at least:
   ```
   DEBUG=False
   SEED_DUMMY_DATA=False
   DJANGO_SECRET_KEY=<a long random string>
   POSTGRES_HOST=<your database host>      # and POSTGRES_PORT/DB/USER/PASSWORD
   BEHIND_TLS_PROXY=True                   # TLS ends at the ingress
   UNGLEICH_SITE_CONFIGS=<your real JSON>
   ```
   plus your OpenNebula, LDAP, Stripe, email and reCAPTCHA values. Leave the Redis URLs alone;
   the manifest creates a service called `redis`.
3. **Store it as a Secret:**
   ```sh
   kubectl create secret generic dynamicweb --from-env-file=<your env file>
   ```
4. **Edit the manifest:** your image name (it appears three times) and the Ingress hosts (one rule
   for each domain, with `www.` variants). Set `ingressClassName` to your controller.
5. **Migrate, then start.** If you have old data, restore it into the empty database first (for
   example `psql -h <host> -U <user> <db> < dump.sql`). Then:
   ```sh
   kubectl apply -f k8s/dynamicweb.yaml
   kubectl logs -f job/dynamicweb-migrate     # takes a few minutes; ends when the Job completes
   kubectl rollout restart deploy/dynamicweb-web
   kubectl logs -f deploy/dynamicweb-web      # ready at "Listening at"
   ```
   The `dynamicweb-migrate` Job runs the migrations once. The web pods don't migrate, so restart
   them after the Job completes (a web pod that started earlier serves errors until you do).
6. **Check:** `curl -I -H 'Host: ungleich.ch' http://<ingress-address>/en-us/` returns 200. Admin
   is at `/en-us/admin/login/` on any site's address.

## Good to know

- **Scaling:** `kubectl scale deploy/dynamicweb-web --replicas=2`, with the media volume changed
  to `ReadWriteMany` so every pod sees the same uploads.
- **Ingress must keep the original `Host` header** (the default). The site is chosen from the
  host, and every domain must be in `UNGLEICH_SITE_CONFIGS` and in `ALLOWED_HOSTS`
  (`dynamicweb/settings/prod.py` lists the current ones).
- **Updating:** push a new image tag, change the image in the manifest, delete the old Job
  (`kubectl delete job dynamicweb-migrate`) and apply again, then restart web.
- **Logs:** `kubectl logs deploy/dynamicweb-web` and `kubectl logs deploy/dynamicweb-celery`.
- **Don't name a Service `postgres` without `enableServiceLinks: false`.** Kubernetes would inject
  `POSTGRES_PORT=tcp://...` and the app crashes. The manifest already sets it on every pod.
