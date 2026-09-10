// Shared helpers for research experiments.
//
// Experiments live next to the brief they support, so they import this by
// relative path — that also makes `pg` resolve from tools/node_modules.
//
// Bring up a scratch PostgreSQL (once per container):
//   sudo -u postgres /usr/lib/postgresql/16/bin/initdb -D /var/lib/postgresql/labdata -U postgres --auth=trust
//   sudo -u postgres /usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/postgresql/labdata -o '-p 5433 -k /tmp' -l /var/lib/postgresql/pg.log start
import pg from "pg";

export const CONN = {
  host: process.env.PGHOST || "/tmp",
  port: Number(process.env.PGPORT || 5433),
  user: process.env.PGUSER || "postgres",
  database: process.env.PGDATABASE || "postgres",
};

export function makePool(max = 24) {
  return new pg.Pool({ ...CONN, max });
}

/** Stand-in for the real-world gap between committing and responding. */
export const work = (ms) => new Promise((r) => setTimeout(r, ms));

export async function serverVersion(pool) {
  const { rows } = await pool.query("select version()");
  return rows[0].version.split(" on ")[0];
}
