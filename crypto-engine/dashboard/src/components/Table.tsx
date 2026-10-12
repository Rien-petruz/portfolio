import { useMemo, useState, type ReactNode } from "react";

export interface Column<T> {
  key: string;
  label: string;
  value?: (row: T) => unknown;          // sort value (defaults to row[key])
  render?: (row: T) => ReactNode;       // cell content
  align?: "left" | "right";
  title?: string;
}

interface Props<T> {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T, i: number) => string;
  initialSort?: { key: string; desc: boolean };
  empty?: string;
  maxRows?: number;
  rowClass?: (row: T) => string | undefined;
}

export function Table<T extends Record<string, unknown>>(p: Props<T>) {
  const [sort, setSort] = useState(p.initialSort ?? { key: p.columns[0].key, desc: false });
  const col = p.columns.find((c) => c.key === sort.key);
  const sorted = useMemo(() => {
    const get = (r: T) => (col?.value ? col.value(r) : r[sort.key]);
    const rows = [...p.rows];
    rows.sort((a, b) => {
      const va = get(a), vb = get(b);
      const na = va === null || va === undefined || (typeof va === "number" && !Number.isFinite(va));
      const nb = vb === null || vb === undefined || (typeof vb === "number" && !Number.isFinite(vb));
      if (na || nb) return na === nb ? 0 : na ? 1 : -1; // missing values always last
      const c = typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb));
      return sort.desc ? -c : c;
    });
    return p.maxRows ? rows.slice(0, p.maxRows) : rows;
  }, [p.rows, sort, col, p.maxRows]);

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {p.columns.map((c) => (
              <th key={c.key} className={c.align === "right" ? "num" : undefined} title={c.title}
                  aria-sort={sort.key === c.key ? (sort.desc ? "descending" : "ascending") : "none"}>
                <button onClick={() => setSort({ key: c.key, desc: sort.key === c.key ? !sort.desc : true })}>
                  {c.label}{sort.key === c.key ? (sort.desc ? " ▾" : " ▴") : ""}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 && (
            <tr><td colSpan={p.columns.length} className="empty">{p.empty ?? "No rows"}</td></tr>
          )}
          {sorted.map((r, i) => (
            <tr key={p.rowKey(r, i)} className={p.rowClass?.(r)}>
              {p.columns.map((c) => (
                <td key={c.key} className={c.align === "right" ? "num" : undefined}>
                  {c.render ? c.render(r) : String(r[c.key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
