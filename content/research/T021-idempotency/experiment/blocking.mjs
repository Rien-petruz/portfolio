// Does the losing INSERT block while the winner's transaction is still open?
//
// This decides whether the key claim may share a transaction with the actual
// work. If losers block, a slow winner stalls every retry behind it — and with
// a connection pool, that is how one slow charge eats the whole pool.
import { makePool } from "../../../../tools/lab.mjs";

const pool = makePool(6);
const setup = async () => {
  await pool.query(`DROP TABLE IF EXISTS k`);
  await pool.query(`CREATE TABLE k (key text PRIMARY KEY, status text)`);
};

async function probe(label, finish) {
  await setup();
  const winner = await pool.connect();
  const loser = await pool.connect();

  await winner.query("BEGIN");
  await winner.query(`INSERT INTO k VALUES ('order-1', 'in_progress')`);
  // winner deliberately does NOT commit yet

  await loser.query("SET statement_timeout = '900ms'");
  const t0 = Date.now();
  let outcome;
  const attempt = loser
    .query(`INSERT INTO k VALUES ('order-1', 'in_progress')
            ON CONFLICT (key) DO NOTHING RETURNING key`)
    .then((r) => (outcome = { rowCount: r.rowCount }))
    .catch((e) => (outcome = { error: e.code === "57014" ? "statement_timeout" : e.code }));

  await new Promise((r) => setTimeout(r, 300));
  const blockedAt300ms = outcome === undefined;
  await finish(winner);
  await attempt;
  const ms = Date.now() - t0;

  console.log(`\n${label}`);
  console.log(`  loser still waiting after 300ms : ${blockedAt300ms}`);
  console.log(`  loser finished after            : ${ms}ms`);
  console.log(`  loser result                    : ${JSON.stringify(outcome)}`);
  const rows = (await pool.query(`SELECT count(*)::int c FROM k`)).rows[0].c;
  console.log(`  rows in table                   : ${rows}`);

  winner.release();
  loser.release();
}

await probe("winner COMMITs after 600ms", async (w) => {
  await new Promise((r) => setTimeout(r, 300));
  await w.query("COMMIT");
});

await probe("winner ROLLBACKs after 600ms", async (w) => {
  await new Promise((r) => setTimeout(r, 300));
  await w.query("ROLLBACK");
});

await pool.end();
