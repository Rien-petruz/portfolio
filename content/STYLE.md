# Copy style rules

These apply to every post: slide copy, titles, descriptions, captions and tags.
They are not suggestions. Check copy against this file before rendering.

## 1. No dashes. Anywhere.

No em dashes, no en dashes, no hyphenated compounds in prose.

| Instead of | Write |
|---|---|
| `It sent one — and retried twice.` | `It sent one, then retried twice.` |
| `One key per intent — not per attempt.` | `One key per intent, not per attempt.` |
| `Attempt 1 — charge committed` | `Attempt 1: charge committed` |
| `a brand-new order` | `a brand new order` |
| `Backend Engineering, daily — follow for more` | `Backend Engineering, daily. Follow for more.` |

Rewrite the sentence rather than swapping the dash for a comma every time.
Full stops are usually stronger anyway.

**The only exceptions**, because changing them would make the content wrong:

- Code and syntax: `Idempotency-Key`, `Content-Type`, `--` SQL comments,
  CLI flags, package names.
- The handle `@peter-kekpe`.
- File and folder names.

Audit before rendering:

```bash
node tools/lint-copy.mjs content/posts/00N-<slug>
```

## 2. Titles are catchy and curious

A title should make someone need to know the answer. It is a hook, not a label.

| Weak, because it labels | Strong, because it opens a loop |
|---|---|
| Idempotency: Make Retries Safe | Why Your API Charged One Customer Three Times |
| Understanding Connection Pools | Your Database Was Fine. Your App Still Died. |
| A Guide To Memory Leaks | Your Server Has 16GB Of RAM And Can't Use It |

Tests a title has to pass:

- Would someone scrolling stop on it?
- Does it imply a specific story rather than a topic?
- No dashes, no colons used as a subtitle joint.

## 3. One tag block for every platform

Do not split tags per platform. Write one combined list and use it everywhere.

Standing core, always present:

```
#BackendEngineering #SystemDesign #SoftwareArchitecture
```

Then add the ones specific to that post's subject, then the reach tags:

```
#SoftwareEngineering #BackendDeveloper #SoftwareEngineer #Programming
#WebDevelopment #DevTips #CodingLife #TechInterview
```

## 4. Every number is measured

If a post states a number, that number came from running code in
`content/research/<topic>/experiment/`, not from an article. This is the whole
edge of the series and it is worth protecting. If a claim cannot be measured,
either cite a primary source or drop it.

## 5. Identity on every slide

Headshot, name and handle render on every slide from the template. Never a per
slide option, never omitted. Any single slide has to work standalone, because
one of them will get screenshotted on its own.
