# T0XX — <topic title>

**Section:** <n>. <section title>
**Status:** researching | researched
**Experiment:** yes / no — `experiment/run.mjs`

---

## 1. Thesis

One paragraph. The thing a senior engineer knows here that a mid-level
engineer doesn't. If this paragraph is generic, the study isn't done.

## 2. Mental model

The mechanism from first principles. What is the OS / database / network /
runtime actually doing? Diagrams in words; the slide art comes later.

## 3. The failure

A concrete production scenario with numbers. What broke, at what scale, and
what the symptom looked like on a dashboard at 3am. Not hypothetical hand-waving.

## 4. Trace it through the stack

Follow one request/operation top to bottom. Name the layer at each step.

## 5. The nitty-gritty

The details that bite. Concurrency, ordering, partial failure, restart
behaviour, clock skew, resource limits. **This section is where the post earns
its keep.** Mark each finding as [measured] or [cited] or [asserted].

## 6. Misconceptions

What most content on this topic gets wrong, and why it's wrong.

## 7. How real systems do it

Stripe / Postgres / Kafka / Linux / nginx — with links.

## 8. Correct implementation

Code that would pass review, with the subtle parts called out in comments.
Include the *wrong* version alongside it if the difference is instructive.

## 9. How to observe it

Metrics, log lines, queries, shell commands. How would you know this is
happening in your own system right now?

## 10. Trade-offs and when not to

Cost, complexity, latency, the cases where the "best practice" is wrong.

## 11. Questions a staff engineer would ask

5–8 questions that separate real understanding from pattern-matching.

## 12. Sources

Links. Primary docs over blog posts.

## 13. Fact-check log

| Claim | Basis |
|---|---|
| ... | measured — `experiment/run.mjs` |
| ... | cited — <link> |
| ... | asserted from general knowledge — verify before publishing |

## 14. Post angle

Which slides this becomes, and the one line that is the hook.
