# Experiment — T021 idempotency

Measures how many charges land when N clients retry the same logical request
concurrently, across four implementations.

## Run it

```bash
# once per container:
sudo -u postgres /usr/lib/postgresql/16/bin/initdb -D /var/lib/postgresql/labdata -U postgres --auth=trust
sudo -u postgres /usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/postgresql/labdata \
  -o '-p 5433 -k /tmp' -l /var/lib/postgresql/pg.log start

node run.mjs          # CLIENTS=20 by default
node blocking.mjs     # does the loser block on an uncommitted winner?
```

Output captured in `results.txt`.

## What it showed

| Variant | Charges for one order |
|---|---|
| no dedupe | 20 |
| check-then-act (SELECT then INSERT) | 20 |
| claim-first (`ON CONFLICT DO NOTHING`) | 1 |

And the two findings that changed the post:

- 19 of 19 concurrent losers found the key `in_progress` with **no stored
  response** — so replaying is impossible and `409` is the correct answer.
- `ON CONFLICT DO NOTHING` blocks until the conflicting transaction resolves
  (~604ms in the probe), so the key claim must not share a transaction with
  the work.
