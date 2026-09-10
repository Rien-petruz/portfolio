# Research standard

No slide gets designed before the topic has a brief in this folder.

The reason is not thoroughness for its own sake. It is that surface-level
technical content is indistinguishable from every other account posting the
same twelve diagrams — and worse, it gets details wrong in ways senior
engineers notice immediately. The brief is where the actual understanding
happens. The carousel is a summary of it.

## The bar

A brief is finished when it can survive a staff engineer reading it. Concretely:

1. **It explains the mechanism, not the API.** Not "use an idempotency key" but
   what the database is doing when two of them arrive in the same millisecond.
2. **Every non-obvious claim is either measured or cited.** Runnable experiment
   in `experiment/`, or a link in Sources. Anything asserted from general
   knowledge is marked as such in the fact-check log.
3. **It names the failure mode the naive version has.** If a brief can't say
   what breaks and under exactly what conditions, the study isn't done.
4. **It covers the case everyone skips.** Usually concurrency, partial failure,
   or what happens on restart. This is where the post gets its edge.
5. **It says when NOT to do this.** Trade-offs, cost, and the situations where
   the "best practice" is the wrong call.

## Prove it, don't assert it

This container has real tooling — use it:

| Tool | Available | Use for |
|---|---|---|
| PostgreSQL 16 | `psql -h /tmp -p 5433 -U postgres` | concurrency, locking, indexes, MVCC, isolation |
| Redis | `redis-server` | queues, caching, distributed locks, expiry |
| Node 22 / Python 3.11 | | event loop, async, GIL, memory |
| gcc, strace, /proc | | syscalls, file descriptors, memory pages, signals |
| Chromium (headless) | | network timing, HTTP/2, TLS |

Bring the scratch database up once per container:

```bash
sudo -u postgres /usr/lib/postgresql/16/bin/initdb -D /var/lib/postgresql/labdata -U postgres --auth=trust
sudo -u postgres /usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/postgresql/labdata \
  -o '-p 5433 -k /tmp' -l /var/lib/postgresql/pg.log start
```

Experiments live in `<topic>/experiment/`, import shared helpers from
`tools/lab.mjs`, and write their output to `results.txt` so the numbers in the
brief are traceable to a command anyone can re-run.

## Layout

```
content/research/
  README.md                  this file
  TEMPLATE.md                the brief skeleton
  T021-idempotency/
    brief.md                 the study
    experiment/
      run.mjs                the code that produced the numbers
      results.txt            captured output
```

## Workflow

```
queued  →  researching  →  researched  →  drafted  →  posted
```

```bash
node tools/status.mjs                          # what's next
node tools/status.mjs T021 researching         # claim it
# ...write content/research/T021-<slug>/brief.md, run experiments
node tools/status.mjs T021 researched
# only now: build slides.json
node tools/render.mjs content/posts/00N-<slug>
node tools/status.mjs T021 drafted 00N-<slug>
node tools/status.mjs T021 posted
```

## Why this matters, concretely

The first draft carousel (post 001, Idempotency) shipped a code sample that
looked correct and was wrong. It did `if (!claim.rowCount) return replay(...)`.
The experiment in `T021-idempotency/experiment/` proved that under 20 concurrent
retries, **19 of the 20 losers find the key marked `in_progress` with no stored
response to replay**. There is nothing to return. Stripe returns `409 Conflict`
in exactly this case.

That bug survived design review. It did not survive twenty lines of test code.
