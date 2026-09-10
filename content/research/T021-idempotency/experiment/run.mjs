// Empirical check for the idempotency brief (T021).
//
// Runs four variants of "N concurrent clients retry the same logical request"
// against a real PostgreSQL server, and counts how many charges actually land.
//
//   node run.mjs            (needs PGHOST/PGPORT/PGUSER pointing at a scratch DB)
//
// Variants
//   1  naive            no dedupe at all
//   2  check-then-act   SELECT, then INSERT if absent   <- the classic wrong fix
//   3  claim-first      INSERT ... ON CONFLICT DO NOTHING RETURNING
//   4  claim-first      same, but measuring what the LOSER sees while the
//                       winner is still in flight
import { makePool, work, serverVersion } from "../../../../tools/lab.mjs";

const CLIENTS = Number(process.env.CLIENTS || 20);
const pool = makePool(CLIENTS + 4);
const q = (sql, args) => pool.query(sql, args);

async function reset() {
  await q(`DROP TABLE IF EXISTS charges, idempotency_keys`);
  await q(`CREATE TABLE charges (id bigserial PRIMARY KEY, order_ref text, amount int)`);
  await q(`CREATE TABLE idempotency_keys (
             key text PRIMARY KEY,
             status text NOT NULL,
             response jsonb,
             created_at timestamptz DEFAULT now())`);
}

const charge = (ref) =>
  q(`INSERT INTO charges (order_ref, amount) VALUES ($1, 5000)`, [ref]);

// 1 — no dedupe
async function naive(key) {
  await charge(key);
}

// 2 — check-then-act: the race lives between the two statements
async function checkThenAct(key) {
  const seen = await q(`SELECT 1 FROM idempotency_keys WHERE key = $1`, [key]);
  if (seen.rowCount > 0) return;
  await work(5); // any latency at all widens the window
  await q(`INSERT INTO idempotency_keys (key, status) VALUES ($1, 'done')
           ON CONFLICT (key) DO NOTHING`, [key]);
  await charge(key);
}

// 3 — claim the key first, let the unique index arbitrate
async function claimFirst(key) {
  const claim = await q(
    `INSERT INTO idempotency_keys (key, status) VALUES ($1, 'in_progress')
     ON CONFLICT (key) DO NOTHING
     RETURNING key`, [key]);
  if (claim.rowCount === 0) return { role: "loser" };
  await work(5);
  await charge(key);
  await q(`UPDATE idempotency_keys SET status='done', response=$2 WHERE key=$1`,
          [key, JSON.stringify({ ok: true })]);
  return { role: "winner" };
}

// 4 — what does the loser actually have to work with?
async function claimFirstInspectLoser(key) {
  const claim = await q(
    `INSERT INTO idempotency_keys (key, status) VALUES ($1, 'in_progress')
     ON CONFLICT (key) DO NOTHING
     RETURNING key`, [key]);
  if (claim.rowCount > 0) {
    await work(40);                       // winner is slow, as real work is
    await charge(key);
    await q(`UPDATE idempotency_keys SET status='done', response=$2 WHERE key=$1`,
            [key, JSON.stringify({ ok: true })]);
    return { role: "winner", saw: "done" };
  }
  const row = await q(`SELECT status, response FROM idempotency_keys WHERE key=$1`, [key]);
  return { role: "loser", saw: row.rows[0].status, hasResponse: row.rows[0].response !== null };
}

async function variant(name, fn, note) {
  await reset();
  const key = `order-${name}`;
  const results = await Promise.all(
    Array.from({ length: CLIENTS }, () => fn(key).catch((e) => ({ error: e.code || e.message })))
  );
  const charges = (await q(`SELECT count(*)::int c FROM charges`)).rows[0].c;
  const errors = results.filter((r) => r && r.error);
  console.log(`\n${name}`);
  console.log(`  ${CLIENTS} concurrent attempts, same key`);
  console.log(`  charges landed : ${charges}${charges === 1 ? "" : "   <-- " + charges + " charges for one order"}`);
  if (errors.length) {
    const kinds = [...new Set(errors.map((e) => e.error))];
    console.log(`  errors         : ${errors.length} (${kinds.join(", ")})`);
  }
  if (note) note(results);
  return charges;
}

console.log(`postgres: ${await serverVersion(pool)}`);
console.log(`concurrency: ${CLIENTS} clients retrying one logical request`);

await variant("1. naive — no dedupe", naive);
await variant("2. check-then-act — SELECT then INSERT", checkThenAct);
await variant("3. claim-first — INSERT ... ON CONFLICT DO NOTHING", claimFirst);
await variant("4. claim-first — what the loser sees", claimFirstInspectLoser, (rs) => {
  const losers = rs.filter((r) => r && r.role === "loser");
  const stale = losers.filter((r) => r.saw === "in_progress");
  console.log(`  losers         : ${losers.length}`);
  console.log(`  losers that found status='in_progress' with no stored response: ${stale.length}`);
  if (stale.length) {
    console.log(`  -> these clients CANNOT replay a response. Returning 200 here is a lie;`);
    console.log(`     the correct answer is 409 Conflict (or wait-and-poll).`);
  }
});

await pool.end();
