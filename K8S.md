# Deploying dynamicweb on Kubernetes

[k8s/dynamicweb.yaml](k8s/dynamicweb.yaml) describes what runs: the web app, the Celery worker,
Redis, a volume for uploaded media, and an Ingress. PostgreSQL 18 is **not** included: use your
own database and point the app at it.

> Not tested on a cluster. The image itself is tested with `docker compose` (see [DOCKER.md](DOCKER.md)).

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
4. **Edit the manifest:** your image name (it appears twice) and the Ingress hosts (one rule for
   each domain, with `www.` variants). Set `ingressClassName` to your controller.
5. **Deploy:**
   ```sh
   kubectl apply -f k8s/dynamicweb.yaml
   kubectl logs -f deploy/dynamicweb-web      # ready at "Listening at"
   ```
   The first start runs the database migrations, so it takes a few minutes.
6. **Check:** `curl -I -H 'Host: ungleich.ch' http://<ingress-address>/en-us/` returns 200. Admin
   is at `/en-us/admin/login/` on any site's address.

## Good to know

- **Run one web replica first.** Each web pod migrates the database when it starts. After the first
  start you can scale (`kubectl scale deploy/dynamicweb-web --replicas=2`), with the media volume
  changed to `ReadWriteMany` so every pod sees the same uploads.
- **Ingress must keep the original `Host` header** (the default). The site is chosen from the
  host, and every domain must be in `UNGLEICH_SITE_CONFIGS` and in `ALLOWED_HOSTS`
  (`dynamicweb/settings/prod.py` lists the current ones).
- **Updating:** push a new image tag, change the image in the manifest and apply it again.
- **Logs:** `kubectl logs deploy/dynamicweb-web` and `kubectl logs deploy/dynamicweb-celery`.
- **Optional hardening:** run the migrations once as a Job instead of in every pod. Use a Job with
  `env: ROLE=migrate`, and add `RUN_MIGRATIONS=False` to the web Deployment.
