---
id: "001"
topicId: T021
topic: "Idempotency: how to prevent duplicate payments/orders"
section: 2, API & Backend Design
slides: 9
formats: portrait 1080x1350 (LinkedIn, Instagram, Facebook) + story 1080x1920 (TikTok)
research: content/research/T021-idempotency/brief.md
---

# Post 001, internal record

Publishing copy lives in `captions.md`. This file is the build record.

## Formula check

| Beat | Slide |
|---|---|
| HOOK | 1. Make retries safe |
| PROBLEM | 2. One customer, three charges |
| REAL SCENARIO | 3. The response died, not the write |
| WHY IT HAPPENS | 4. The retry storm |
| ARCHITECTURE / SOLUTION | 5. Give every attempt a name |
| | 6. The loser has nothing to replay |
| | 7. Claim the key first |
| | 8. Two retries, one row |
| TAKEAWAY | 9. A retry is the same intent, asking again |

## Claims made in this post, and where they came from

| Claim | Source |
|---|---|
| 20 concurrent retries, no dedupe: 20 charges | measured, `experiment/run.mjs` |
| Check then act: 20 charges, no protection | measured, `experiment/run.mjs` |
| Claim first: 1 charge | measured, `experiment/run.mjs` |
| 19 of 20 losers see `in_progress`, nothing to replay | measured, `experiment/run.mjs` |
| Stripe returns 409 for an in flight duplicate key | cited, Stripe API reference |

## Notes

Slide 7 originally shipped `if (!claim.rowCount) return replay(res, key)`.
The experiment disproved it. See brief section 5.4.
