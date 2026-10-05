# Old-version database snapshot

`django-1.9.sql.gz` is a dump of the sample database made on the original
Django 1.9 stack (no real or personal data). It stands in for an old
production database: after each upgrade step, restore it and let the new
version migrate it.

```sh
sh legacy-snapshot/restore.sh
docker compose exec web python smoke_test.py   # after the site answers (~1.5 min)
```

It holds the sample sites and pages from `seed_dummy_data` plus what
`seed_extra.py` adds: blog posts, contact messages, hosting plans and
supporters. Real production rows are the one thing it cannot cover.
