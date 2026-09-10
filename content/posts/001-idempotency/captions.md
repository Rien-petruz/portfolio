# Post 001, copy for publishing

**Topic:** T021 Idempotency
**Assets:** `out/portrait/01..09.png` (LinkedIn, Instagram, Facebook),
`out/story/01..09.png` (TikTok), `out/linkedin.pdf`

Style rules for this file live in `content/STYLE.md`.

---

## Title

**Why Your API Charged One Customer Three Times**

Alternates:
- Your Logs Say 200. Your Customer Paid Three Times.
- The Bug Your Dashboard Will Never Show You
- What Really Happens When A Request Times Out
- The Idempotency Mistake In Almost Every Tutorial

## Short description

> Your payment API charged one customer three times, and every request logged a
> 200. Nothing looked wrong. Here is what actually broke, and the one line of
> SQL that fixes it properly.

One line version:

> A timeout doesn't mean it failed. It means you don't know.

---

## Caption

Your payment API charged one customer three times last night.

The client didn't send three requests. It sent one, then retried twice.

Here is the part most developers miss. A timeout tells you the response is
missing. It never tells you the write didn't happen. Your server committed the
charge, then the connection dropped before the response got back. The client
did the only sensible thing it could. It tried again.

And every one of those duplicate charges logged a 200. There was no error to
alert on. The dashboard was green. Support found out before monitoring did.

The instinctive fix is to check whether the order already exists, then insert
if it doesn't. That doesn't work. I tested it: 20 concurrent retries produced
20 duplicate charges. Zero protection.

What works is claiming an idempotency key with the write itself, so the unique
index does the arbitration instead of your application code. Same test, same
concurrency: 1 charge.

But there is a trap in the version you will find in most tutorials. They replay
the stored response to the losing request. I measured that too. 19 of 20 losers
found the key marked in_progress with nothing stored, because the winner hadn't
finished yet. Returning 200 there tells the client the payment succeeded before
it actually has.

The correct answer is 409 Conflict. It is what Stripe returns in exactly this
situation.

A retry is not a new request. It is the same intent, asking again.

Design every write endpoint so the second attempt is boring.

Every number in this post came from running the code, not from reading about
it. Save it for your next system design interview.

## Tags

#BackendEngineering #SystemDesign #SoftwareArchitecture #DistributedSystems #APIDesign #Database #PostgreSQL #SoftwareEngineering #BackendDeveloper #SoftwareEngineer #Programming #WebDevelopment #DevTips #CodingLife #TechInterview
