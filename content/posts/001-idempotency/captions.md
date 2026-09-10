# Post 001 — copy for publishing

**Topic:** T021 Idempotency
**Assets:** `out/portrait/01–09.png` (LinkedIn · Instagram · Facebook),
`out/story/01–09.png` (TikTok), `out/linkedin.pdf`

---

## Title

**Idempotency: Make Retries Safe**

Alternates, if you want a sharper hook:
- Why Your API Charged That Customer Three Times
- A Timeout Is Not a Failure
- The Idempotency Bug That's in Almost Every Tutorial

## Short description

> Your payment API charged one customer three times — and every request logged
> a 200. Here's what actually broke, and the one-line database trick that fixes
> it properly.

One-liner version (TikTok / IG bio-style):

> A timeout doesn't mean it failed. It means you don't know.

---

## LinkedIn

Your payment API charged one customer three times last night.

The client didn't send three requests. It sent one — and retried twice.

Here's the part most developers miss: a timeout tells you the response is
missing. It never tells you the write didn't happen. Your server committed the
charge, then the connection dropped before the response got back. The client
did the only sensible thing it could. It tried again.

And every single one of those duplicate charges logged a 200. There was no
error to alert on. The dashboard was green.

The instinctive fix — "check if it exists, then insert" — doesn't work. I
tested it: 20 concurrent retries, 20 duplicate charges. Zero protection.

What works is claiming an idempotency key with the write itself, so the unique
index does the arbitration instead of an if-statement in your code. Same test:
1 charge.

But there's a trap in the version you'll find in most tutorials. They replay
the stored response to the losing request. I measured that too — 19 of 20
losers found the key marked in_progress with nothing stored, because the winner
hadn't finished yet. Returning 200 there tells the client the payment succeeded
before it actually has.

The correct answer is 409 Conflict. It's what Stripe returns in exactly this
case.

A retry is not a new request. It is the same intent, asking again.

Design every write endpoint so the second attempt is boring.

#BackendEngineering #SystemDesign #SoftwareArchitecture #DistributedSystems #APIDesign

---

## Instagram

Your API charged one customer three times.
And every request logged a 200. 👀

A timeout doesn't mean it failed.
It means you don't know.

→ "Check if it exists first" = 20 retries, 20 duplicate charges
→ Claim the key with the write = 1 charge
→ And the bit almost every tutorial gets wrong: the second request has nothing
to replay. It needs a 409, not a 200.

A retry isn't a new request.
It's the same intent, asking again.

Save this one for your next system design interview 🔖

#backend #backenddeveloper #systemdesign #softwarearchitecture #distributedsystems
#api #apidesign #database #postgresql #softwareengineering #codinglife #devtips
#programming #webdevelopment #techinterview

---

## Facebook

Your payment API charged one customer three times — and every request logged a
200, so nothing looked wrong.

The client only sent one request. It retried twice, because it timed out
waiting for a response that got lost after the charge had already committed.

A timeout tells you the response is missing. It never tells you the write
didn't happen. That's the whole problem.

I tested the usual fixes. "Check if it exists first" gave 20 duplicate charges
out of 20 concurrent retries — no protection at all. Claiming an idempotency
key with the write itself gave exactly 1.

Full breakdown in the carousel, including the mistake that's in almost every
tutorial on this topic.

#BackendEngineering #SystemDesign #SoftwareEngineering #APIDesign

---

## TikTok

Your API charged them 3 times and logged a 200 every time 💀

A timeout doesn't mean it failed — it means you don't know.

"Check if it exists first" → 20 retries, 20 charges.
Claim the key with the write → 1 charge.

Swipe for the one almost every tutorial gets wrong 👉

#backenddeveloper #systemdesign #codingtips #softwareengineer #programmingtips #techtok

---

## Tag reference

**Core (always):** #BackendEngineering #SystemDesign #SoftwareArchitecture
**This post:** #DistributedSystems #APIDesign #Database #PostgreSQL
**Reach (IG/TikTok):** #softwareengineer #programming #devtips #codinglife #techtok #techinterview

Per-platform counts that work: LinkedIn 3–5, Facebook 3–5, TikTok 4–6,
Instagram 10–15.
