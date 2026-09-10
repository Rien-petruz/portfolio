# T021 — Idempotency: how to prevent duplicate payments/orders

**Section:** 2. API & Backend Design
**Status:** researched
**Experiment:** yes — `experiment/run.mjs`, `experiment/blocking.mjs`, output in `experiment/results.txt`
**Environment:** PostgreSQL 16.13, Node 22, 20 concurrent clients

---

## 1. Thesis

Idempotency is not a deduplication feature. It is a way of making *"I don't
know whether that worked"* into a recoverable state.

A client that gets a timeout has learned exactly one thing: the response is
missing. It has learned nothing about whether the write happened. Those are
different events on different sides of the network, and they fail
independently. Every distributed system eventually has to answer "what does a
caller do when it doesn't know?" — and the only safe answer is "ask again, in a
way that cannot make things worse."

The interesting engineering is not the key. Generating a UUID is not the hard
part. The hard part is the window between *claiming* the key and *finishing*
the work, because that window is where all the real bugs live — and it is the
part almost every article on this topic skips.

## 2. Mental model

Any request has three outcomes from the client's point of view:

1. **Success** — response received, status known.
2. **Definite failure** — connection refused, DNS failure, 400. Nothing ran.
3. **Unknown** — timeout, connection reset, 502, 504. Something *may* have run.

Only outcome 3 matters. And outcome 3 is not rare: it is the normal
steady-state behaviour of any system with a load balancer, a proxy, a mobile
client, or a deploy.

The critical asymmetry: **a response is not an acknowledgement of a write.**
The write commits inside your database. The response travels back through your
app, your reverse proxy, your load balancer, the internet, and a mobile radio.
Any of those hops can drop it *after* the money moved.

So the server needs a durable record of *intent*, keyed by something the client
chose **before its first attempt**, so that all attempts — first and retried —
name the same intent. That is the whole idea. The key is not an identifier for
the request. It is an identifier for the *intent behind* the request.

## 3. The failure

A payments endpoint, no idempotency. A mobile client with a 10-second socket
timeout sitting behind an ALB with a 60-second idle timeout.

Card processing takes 11 seconds under load. The client times out at 10s and
retries. The charge from attempt 1 commits at 11s. Attempt 2 commits at 22s.
Attempt 3 at 33s. The customer is charged three times, the client eventually
shows an error, and support hears about it before your monitoring does —
because every one of those requests was a **200 in your logs**.

That last detail is what makes this class of bug so expensive. There is no
error to alert on. Your success rate is 100%. The dashboard is green.

## 4. Trace it through the stack

```
client  ──POST /payments──▶ LB ──▶ app ──▶ DB
                                             │  BEGIN; INSERT charge; COMMIT  ← money moves here
                                             ▼
                                          committed
        ◀──── 201 ────  app  ◀──────────────┘
          ✗ lost here: LB idle timeout fired, client socket closed,
            radio dropped, proxy 504'd, pod was evicted mid-response
client times out ──▶ retries ──▶ (repeat, money moves again)
```

Every layer has its own independent timeout, and none of them can cancel work
already committed downstream:

| Layer | Typical timeout | What it does on expiry |
|---|---|---|
| Mobile/HTTP client | 10–30s | gives up, retries |
| CDN / API gateway | ~29s (AWS API GW hard limit) | returns 504 |
| Load balancer | 60s idle default (ALB) | drops connection |
| App server | often none | keeps working |
| Database | often none | keeps working |

The bottom two rows are the problem. **The work outlives the caller.**

## 5. The nitty-gritty

All of the following was measured against a real PostgreSQL 16.13 with 20
concurrent clients retrying one logical request. Re-run with
`node experiment/run.mjs`.

### 5.1 The naive version charges once per attempt — [measured]

```
1. naive — no dedupe
   charges landed : 20
```

### 5.2 Check-then-act does not help at all — [measured]

The instinctive fix — "look it up first, insert if it's missing" — is a race
with itself. The gap between the `SELECT` and the `INSERT` is the whole bug,
and any latency at all widens it:

```
2. check-then-act — SELECT then INSERT
   charges landed : 20
```

Twenty out of twenty. Not "usually fine, occasionally a duplicate" — under
concurrency it provides **zero** protection. This is the single most common
wrong fix in production code.

### 5.3 Claiming the key first works — [measured]

```
3. claim-first — INSERT ... ON CONFLICT DO NOTHING
   charges landed : 1
```

The arbitration is done by the unique index, inside the database, at the point
where the row is written. Not by an `if` statement in your application. There
is no window to race in, because the check and the write are the same operation.

### 5.4 The loser has nothing to replay — [measured] ⚠️

This is the finding that matters, and the one that was wrong in the first
draft of the carousel:

```
4. claim-first — what the loser sees
   losers         : 19
   losers that found status='in_progress' with no stored response: 19
```

Nineteen of nineteen. When retries arrive *concurrently* — which is the normal
case, not the exotic one — the losing requests find the key already claimed
and marked `in_progress`, **with no stored response**, because the winner
hasn't finished yet.

So this, which is what most tutorials show, is a bug:

```js
if (claim.rowCount === 0) return replayStoredResponse(res, key);   // ✗ nothing stored yet
```

There is no response to replay. Returning `200` here is a lie — you'd be
telling the client the payment succeeded before it has. The correct answer is
`409 Conflict`, which is [exactly what Stripe returns](https://docs.stripe.com/api/idempotent_requests)
in this case. Replay is only valid when the stored status is `done`.

### 5.5 Losers block on an uncommitted winner — [measured] ⚠️

From `experiment/blocking.mjs`:

```
winner COMMITs after 600ms
  loser still waiting after 300ms : true
  loser finished after            : 603ms
  loser result                    : {"rowCount":0}

winner ROLLBACKs after 600ms
  loser finished after            : 603ms
  loser result                    : {"rowCount":1}    ← loser now wins the key
```

`ON CONFLICT DO NOTHING` **waits** on a conflicting row that another
transaction has inserted but not yet committed. It cannot decide whether there
is a conflict until that transaction resolves.

Two consequences, both important:

- **Never hold the key claim in the same transaction as the work.** If you do,
  every retry blocks for the full duration of the charge. Each blocked retry is
  holding a pooled connection while it waits. A slow payment provider plus a
  retrying client is now a connection-pool exhaustion incident — which is how
  one slow dependency takes down endpoints that have nothing to do with
  payments. Commit the claim in its own short transaction, then do the work.
- **Rollback correctly frees the key.** If the winner's transaction aborts, the
  next attempt wins the claim and proceeds. That is the recovery path working
  as intended.

### 5.6 The crash window — [asserted, design-level]

If the process dies between "charge committed" and "response stored", the key
is left `in_progress` forever. Every subsequent retry gets a `409` and the
customer can never complete the order.

The claim therefore needs a **lease**, not just a flag: store `locked_until`,
and let a later attempt take over an expired claim. This turns a permanent
wedge into a bounded one. Recovery still has to reconcile whether the charge
actually landed, which is why the response should be written in the *same
transaction* as the side effect wherever the side effect is local.

Where the side effect is a third-party call, it cannot be transactional — and
that is the honest limit of this pattern. You reduce the unknown window, you
don't eliminate it.

### 5.7 Same key, different body

If a client reuses a key with different parameters, that is a client bug, and
silently returning the first response hides it. Stripe stores a fingerprint of
the original parameters and errors if they differ. Do the same: hash the body,
store the hash with the key, return `422` on mismatch.

### 5.8 Key scope

A key is only unique within a scope. Scope it to `(endpoint, account_id, key)`,
not the bare key. Otherwise one tenant's key can collide with another's, and
you have built a cross-tenant data leak instead of a safety feature.

### 5.9 Retention

Stripe removes keys after at least 24 hours, and
[a key reused after pruning starts a new request](https://docs.stripe.com/api/idempotent_requests).
This is a deliberate trade: unbounded key storage is a cost and a growing
index. Pick a window longer than any client's total retry budget.

## 6. Misconceptions

| Claim you'll see | Why it's wrong |
|---|---|
| "Check if it exists, then insert." | Measured: 20/20 duplicates under concurrency. Zero protection. |
| "The loser replays the stored response." | Measured: 19/19 losers had nothing stored. Must be `409`. |
| "Retries are the problem — retry less." | Retries are correct behaviour. The server is what's broken. |
| "Idempotency gives you exactly-once." | It gives at-least-once *delivery* with at-most-once *effect*. Different, and the difference matters. |
| "Use a distributed lock (Redis/Zookeeper)." | Your database already has a correct, durable, crash-safe one: the unique index. Adding a second consensus system adds a second failure mode. |
| "Just put a unique constraint on `order_id`." | Half-right. It prevents the duplicate row but gives the client a constraint-violation error instead of the original response — so the client still doesn't know if it worked. |
| "Only payments need this." | Anything that isn't naturally idempotent: sending email, incrementing a counter, allocating inventory, calling a partner API. |

## 7. How real systems do it

- **Stripe** — `Idempotency-Key` header on all POSTs, keys up to 255 chars,
  results retained at least 24h, `409` while a request with the same key is in
  flight, parameter fingerprinting to reject reuse with different bodies.
  ([API reference](https://docs.stripe.com/api/idempotent_requests))
- **Brandur Leach (Stripe)** — the canonical writeup of the Postgres
  implementation, including the phased state machine and recovery points.
  ([brandur.org/idempotency-keys](https://brandur.org/idempotency-keys))
- **PostgreSQL** — `INSERT ... ON CONFLICT DO NOTHING` uses speculative
  insertion, which is why it blocks on an uncommitted conflicting row rather
  than guessing. Measured above.
- **HTTP itself** — `PUT` and `DELETE` are defined as idempotent methods;
  `POST` is not. The whole pattern is a way of giving `POST` the property the
  spec gives `PUT`.

## 8. Correct implementation

```js
// Step 1 — claim the key in its own short transaction.
//          NOT in the same transaction as the charge: see 5.5, a slow winner
//          would block every retry and exhaust the connection pool.
const claim = await db.query(
  `INSERT INTO idempotency_keys (scope, key, request_hash, status, locked_until)
   VALUES ($1, $2, $3, 'in_progress', now() + interval '60 seconds')
   ON CONFLICT (scope, key) DO UPDATE
     SET locked_until = excluded.locked_until          -- take over an expired lease
     WHERE idempotency_keys.locked_until < now()
       AND idempotency_keys.status = 'in_progress'
   RETURNING status`,
  [scope, key, hashOf(req.body)]
);

if (claim.rowCount === 0) {
  const prior = await db.query(
    `SELECT status, request_hash, response_code, response_body
       FROM idempotency_keys WHERE scope = $1 AND key = $2`, [scope, key]);
  const row = prior.rows[0];

  if (row.request_hash !== hashOf(req.body))      // 5.7 — client bug, don't hide it
    return res.status(422).json({ error: 'idempotency key reused with different parameters' });

  if (row.status === 'in_progress')               // 5.4 — nothing to replay yet
    return res.status(409).json({ error: 'request already in progress' });

  return res.status(row.response_code).json(row.response_body);   // genuine replay
}

// Step 2 — do the work, and store the response in the SAME transaction as the
//          side effect so they cannot diverge (5.6).
const tx = await db.begin();
try {
  const payment = await tx.query(`INSERT INTO charges (...) VALUES (...) RETURNING *`);
  await tx.query(
    `UPDATE idempotency_keys SET status='done', response_code=201, response_body=$3
      WHERE scope=$1 AND key=$2`, [scope, key, payment.rows[0]]);
  await tx.commit();
  return res.status(201).json(payment.rows[0]);
} catch (e) {
  await tx.rollback();                            // 5.5 — frees the key for the next attempt
  throw e;
}
```

The version that ships in most tutorials, for contrast:

```js
const claim = await db.query(
  `INSERT INTO idempotency_keys (key, status) VALUES ($1, 'in_progress')
   ON CONFLICT (key) DO NOTHING RETURNING key`, [key]);
if (claim.rowCount === 0) return replayStoredResponse(res, key);   // ✗ 19/19 have nothing to replay
```

## 9. How to observe it

```sql
-- Keys wedged in_progress: crash window, or a lease that is too long.
SELECT scope, key, age(now(), created_at) AS stuck_for
FROM idempotency_keys
WHERE status = 'in_progress' AND locked_until < now()
ORDER BY created_at;
```

```sql
-- Are you charging the same intent more than once, right now?
SELECT order_ref, count(*) FROM charges
GROUP BY order_ref HAVING count(*) > 1;
```

Metrics worth having:

- `idempotency_replay_total` — retries that correctly replayed. Should be
  non-zero. **Zero means the mechanism is not being exercised, not that it's
  working.**
- `idempotency_conflict_total` — the `409`s. A spike means clients are
  retrying concurrently, usually because something downstream got slow.
- `idempotency_keys_stuck` — gauge from the query above. Should be ~0.
- `idempotency_hash_mismatch_total` — client bugs. Should be 0.

## 10. Trade-offs and when not to

- Costs one extra write on **every** mutating request, plus an index and a
  growing table that needs pruning.
- Adds a second round trip before any work starts — real latency, on the hot path.
- Pointless for naturally idempotent operations. `SET status = 'paid'` is
  already idempotent; `balance = balance + 100` is not. Know which one you wrote.
- Pointless for reads.
- Does **not** solve the third-party problem. If your side effect is someone
  else's API, you need *their* idempotency guarantee too — you can only make
  your side of the boundary safe.
- For very high write rates, the key table becomes a hot spot. Partition by
  time and drop old partitions rather than `DELETE`-ing rows.

## 11. Questions a staff engineer would ask

1. Where does the key come from, and why must the client generate it before the
   *first* attempt rather than the server generating it?
2. What does the second concurrent request receive, and why is `200` wrong?
3. Why can't the key claim share a transaction with the work?
4. What happens if the process is killed between the charge and storing the
   response? How does the system recover, and how long does it stay broken?
5. Same key, different request body — what do you return, and why does silently
   replaying hide a bug?
6. How long do you retain keys, and what happens to a client that retries after
   that window?
7. Does this give you exactly-once semantics? If not, what does it give you?
8. Your dashboard shows 100% success. How would you find out that you are
   double-charging customers right now?

## 12. Sources

- Stripe — [Idempotent requests, API reference](https://docs.stripe.com/api/idempotent_requests)
- Brandur Leach — [Implementing Stripe-like idempotency keys in Postgres](https://brandur.org/idempotency-keys)
- PostgreSQL — [INSERT ... ON CONFLICT](https://www.postgresql.org/docs/current/sql-insert.html)
- Local measurements — `experiment/results.txt`

## 13. Fact-check log

| Claim | Basis |
|---|---|
| Naive endpoint charges once per retry (20/20) | measured — `experiment/run.mjs` |
| Check-then-act gives zero protection (20/20) | measured — `experiment/run.mjs` |
| Claim-first yields exactly 1 charge | measured — `experiment/run.mjs` |
| 19/19 concurrent losers see `in_progress`, nothing to replay | measured — `experiment/run.mjs` |
| `ON CONFLICT DO NOTHING` blocks on an uncommitted conflicting insert (~604ms) | measured — `experiment/blocking.mjs` |
| Winner rollback frees the key to the next attempt | measured — `experiment/blocking.mjs` |
| Stripe retains keys ≥24h; reuse after pruning starts a new request | cited — Stripe API reference |
| Stripe returns 409 while a same-key request is in flight | cited — Stripe API reference / Brandur |
| AWS API Gateway ~29s hard timeout, ALB 60s idle default | asserted from general knowledge — **verify before publishing** |
| Blocked retries holding pooled connections cause pool exhaustion | reasoned from 5.5 — mechanism measured, the incident chain is inference |

## 14. Post angle

**Hook:** the payment API returned 200 three times and the customer was charged
three times — and nothing in your logs looks wrong.

The strongest slide is not the solution. It is 5.2: *check-then-act gives you
20 duplicates out of 20 attempts.* Most of the audience has written exactly
that code and believes it works. Leading with the measured number earns the
rest of the carousel.

Second strongest is 5.4 — the loser has nothing to replay — because it is the
correction to the version of this advice that is already everywhere.

**Correction required to post 001:** slide 6 currently shows
`if (!claim.rowCount) return replay(res, key)`. That is the bug this brief
disproves. It must show the `409` branch. Do not publish 001 as drafted.
