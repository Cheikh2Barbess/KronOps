"use client";

// Courbes, barres et tableaux du tableau de bord, en SVG et HTML simples (aucune bibliotheque ajoutee).
// Couleurs des series : 3 teintes fixes dans le meme ordre (bleu, orange, turquoise), toujours avec une legende.
// Couleurs d'etat (vert, jaune, rouge) : toujours avec icone et mot (components/Status.tsx).
import { Status, StatusBadge, StatusIcon, STATUS_META } from "@/components/Status";

export type Cell = string | number | { text: string | number; status: Status };
export type Point = { x: string; y: number | null };
export type Series = { name: string; points: Point[]; band?: { min: number; max: number } };
export type Detail =
  | { kind: "line"; title: string; unit: string; series: Series[] }
  | { kind: "bars"; title: string; unit: string; bars: { label: string; value: number | null; status?: Status }[] }
  | { kind: "table"; title: string; columns: string[]; rows: Cell[][] };

const SERIES = ["#257de0", "#f47230", "#00a383", "#6a4ce2", "#008a17"];
const nf = (n: number | null | undefined, unit = "") =>
  n === null || n === undefined ? "Aucune donnée" : `${n.toLocaleString("fr-FR", { maximumFractionDigits: 1 })}${unit ? ` ${unit}` : ""}`;

export function CellView({ cell }: { cell: Cell }) {
  if (cell !== null && typeof cell === "object") return <StatusBadge status={cell.status} text={String(cell.text)} />;
  return <>{typeof cell === "number" ? cell.toLocaleString("fr-FR") : cell}</>;
}

export function DataTable({ columns, rows }: { columns: string[]; rows: Cell[][] }) {
  if (!rows.length) return <p>Rien à afficher.</p>;
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="detail-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j}>
                  <CellView cell={cell} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function LineChart({ series, unit }: { series: Series[]; unit: string }) {
  const W = 900, H = 300, L = 56, R = 16, T = 14, B = 36;
  const labels = series[0]?.points.map((p) => p.x) || [];
  const values = series.flatMap((s) => [...s.points.map((p) => p.y), s.band?.min ?? null, s.band?.max ?? null]).filter((v): v is number => v !== null);
  if (!labels.length || !values.length) return <p>Aucune donnée sur la période.</p>;
  const max = Math.max(...values) * 1.1 || 1;
  const min = Math.min(0, ...values);
  const x = (i: number) => L + (labels.length === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (labels.length - 1));
  const y = (v: number) => T + (H - T - B) * (1 - (v - min) / (max - min));
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => min + f * (max - min));
  const every = Math.ceil(labels.length / 12);
  return (
    <figure style={{ margin: 0 }}>
      {series.length > 1 && (
        <div className="chart-legend">
          {series.map((s, i) => (
            <span key={s.name}>
              <i style={{ background: SERIES[i % SERIES.length] }} />
              {s.name}
            </span>
          ))}
        </div>
      )}
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`Courbe en ${unit}`} style={{ maxHeight: 360 }}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke="#e5e7eb" />
            <text x={L - 6} y={y(t) + 4} textAnchor="end" fontSize="12" fill="#4b5563">
              {nf(Math.round(t * 10) / 10)}
            </text>
          </g>
        ))}
        {series.map((s, i) =>
          s.band ? (
            <rect key={`band-${s.name}`} x={L} width={W - L - R} y={y(s.band.max)} height={Math.max(1, y(s.band.min) - y(s.band.max))}
              fill={SERIES[i % SERIES.length]} opacity={0.1}>
              <title>{`${s.name} : fourchette ${nf(s.band.min)} à ${nf(s.band.max, unit)}`}</title>
            </rect>
          ) : null,
        )}
        {labels.map((lab, i) =>
          i % every === 0 ? (
            <text key={lab} x={x(i)} y={H - 12} textAnchor="middle" fontSize="12" fill="#4b5563">
              {lab}
            </text>
          ) : null,
        )}
        {series.map((s, si) => {
          const color = SERIES[si % SERIES.length];
          // Une periode sans valeur coupe la ligne (pas d'invention entre deux mesures).
          const segments: string[] = [];
          let current = "";
          s.points.forEach((p, i) => {
            if (p.y === null) {
              if (current) segments.push(current);
              current = "";
            } else current += `${current ? "L" : "M"}${x(i)},${y(p.y)}`;
          });
          if (current) segments.push(current);
          return (
            <g key={s.name}>
              {segments.map((d, k) => (
                <path key={k} d={d} fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" />
              ))}
              {s.points.map((p, i) =>
                p.y === null ? null : (
                  <g key={i}>
                    <circle cx={x(i)} cy={y(p.y)} r={4.5} fill={color} stroke="#fff" strokeWidth={2} />
                    <circle cx={x(i)} cy={y(p.y)} r={12} fill="transparent">
                      <title>{`${s.name}, ${p.x} : ${nf(p.y, unit)}`}</title>
                    </circle>
                  </g>
                ),
              )}
            </g>
          );
        })}
      </svg>
      <details>
        <summary>Voir les valeurs en tableau</summary>
        <DataTable
          columns={["Période", ...series.map((s) => `${s.name} (${unit})`)]}
          rows={labels.map((lab, i) => [lab, ...series.map((s) => nf(s.points[i]?.y))])}
        />
      </details>
    </figure>
  );
}

export function Bars({ bars, unit }: { bars: { label: string; value: number | null; status?: Status }[]; unit: string }) {
  if (!bars.length) return <p>Aucune donnée.</p>;
  const max = Math.max(...bars.map((b) => b.value || 0)) || 1;
  return (
    <div style={{ display: "grid", gap: 6 }}>
      {bars.map((b) => {
        const color = b.status ? STATUS_META[b.status].border : SERIES[0];
        return (
          <div key={b.label} style={{ display: "grid", gridTemplateColumns: "minmax(120px, 220px) 1fr", gap: 10, alignItems: "center" }}>
            <span>{b.label}</span>
            <span style={{ display: "flex", alignItems: "center", gap: 8 }} title={`${b.label} : ${nf(b.value, unit)}`}>
              <span style={{ height: 18, width: `${Math.max(1, ((b.value || 0) * 100) / max)}%`, maxWidth: "75%", background: color, borderRadius: "0 4px 4px 0" }} />
              <span style={{ whiteSpace: "nowrap", display: "inline-flex", gap: 4, alignItems: "center" }}>
                {b.status && <StatusIcon status={b.status} />}
                {nf(b.value, unit)}
                {b.status && <span className="sr-only">{STATUS_META[b.status].label}</span>}
              </span>
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function DetailView({ detail }: { detail: Detail }) {
  return (
    <section className="detail-block">
      <h3>{detail.title}</h3>
      {detail.kind === "line" && <LineChart series={detail.series} unit={detail.unit} />}
      {detail.kind === "bars" && <Bars bars={detail.bars} unit={detail.unit} />}
      {detail.kind === "table" && <DataTable columns={detail.columns} rows={detail.rows} />}
    </section>
  );
}

// Petite courbe dans la tuile : la premiere serie de la premiere courbe du detail.
export function Sparkline({ series }: { series: Series[] }) {
  const pts = series[0]?.points || [];
  const vals = pts.map((p) => p.y).filter((v): v is number => v !== null);
  if (vals.length < 2) return null;
  const W = 220, H = 36;
  const max = Math.max(...vals) || 1, min = Math.min(0, ...vals);
  const d = pts
    .map((p, i) => (p.y === null ? null : `${(i * W) / (pts.length - 1)},${H - 3 - ((p.y - min) * (H - 6)) / (max - min || 1)}`))
    .filter(Boolean)
    .map((c, i) => `${i ? "L" : "M"}${c}`)
    .join("");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} aria-hidden="true">
      <path d={d} fill="none" stroke={SERIES[0]} strokeWidth={2} />
    </svg>
  );
}
