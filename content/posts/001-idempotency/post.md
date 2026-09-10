---
id: "001"
topicId: T021
topic: "Idempotency: how to prevent duplicate payments/orders"
section: 2 — API & Backend Design
slides: 8
format: square (1080x1080)
---

# Idempotency: Make retries safe.

## Caption

Your payment API charged one customer three times last night.

The client didn't send three requests. It sent one — and retried twice.

Here's what actually happened. Your server committed the charge and started
writing the response. The connection dropped before that response got back.
The client saw a timeout and did the only sensible thing it could do: it tried
again. Twice.

This is the part developers miss. A timeout tells you the response is missing.
It never tells you the write didn't happen.

So the fix isn't "retry less." Retries are correct — the network genuinely does
lose responses. The fix is making the second attempt land on the same outcome
as the first.

Give every attempt a name. The client generates one key per *intent* — not per
attempt — and sends that same key on every retry:

    Idempotency-Key: 7c9e-4f21-b03a

Then, server side, claim the key *before* you do the work:

    INSERT INTO idempotency_keys (key, status)
    VALUES ($1, 'in_progress')
    ON CONFLICT (key) DO NOTHING
    RETURNING id

If the INSERT returns nothing, this is a retry — replay the stored response
instead of charging again.

The detail that makes this actually safe: the arbitration is done by a unique
index, not by an if-statement in your application. Two retries arriving in the
same millisecond both hit that index. Exactly one survives. No lock, no queue,
no distributed coordinator.

A retry is not a new request. It is the same intent, asking again.

Design every write endpoint so the second attempt is boring.

---

Backend Engineering & System Architecture — daily.
Follow for the next one.

## Hashtags

#backend #systemdesign #softwarearchitecture #api #distributedsystems
#engineering #softwareengineering #webdevelopment #databases #payments

## Formula check

| Beat | Where |
|---|---|
| HOOK | Slide 1 — "Make retries safe." |
| PROBLEM | Slide 2 — one customer, three charges |
| REAL SCENARIO | Slide 3 — the response died, not the write |
| WHY IT HAPPENS | Slide 4 — the retry storm |
| ARCHITECTURE / SOLUTION | Slides 5–7 — idempotency key, claim-first, unique index |
| TAKEAWAY | Slide 8 — a retry is the same intent, asking again |
