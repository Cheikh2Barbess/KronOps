"use client";

// Courbes, barres et tableaux du tableau de bord, en SVG et HTML simples (aucune bibliotheque ajoutee).
// Regles de lecture :
// - un graphique = une question. Le titre affiche la reponse (calculee des donnees), la question vient dessous ;
// - une seule couleur mise en avant (la serie la plus importante), les autres en gris ;
// - le nom de chaque courbe est ecrit au bout de la ligne, pas dans une legende a part ;
// - chiffres arrondis, sans decimale au-dela de 100.
// Couleurs d'etat (vert, jaune, rouge) : toujours avec icone et mot (components/Status.tsx).
import { useMemo, useState } from "react";
import { Icon } from "@/components/Icon";
import { Status, StatusBadge, StatusIcon, STATUS_META } from "@/components/Status";

export type Cell = string | number | { text: string | number; status: Status };
export type Point = { x: string; y: number | null };
// `target` : serie de cible (Sollwert), dessinee en pointilles gris, jamais mise en avant.
export type Series = { name: string; points: Point[]; band?: { min: number; max: number }; target?: boolean };
export type Bar = { label: string; value: number | null; status?: Status };
// aggregate : "sum" (kilos par periode), "mean" (pourcentages, heures), "cumul" (total qui s'accumule).
export type Detail =
  | { kind: "line"; title: string; unit: string; series: Series[]; aggregate?: "sum" | "mean" | "cumul" }
  | { kind: "bars"; title: string; unit: string; bars: Bar[] }
  | { kind: "table"; title: string; columns: string[]; rows: Cell[][] }
  | { kind: "tabs"; title: string; tabs: { label: string; details: Detail[] }[] };

const HIGHLIGHT = "#2e6be6";
const OTHERS = ["#98a2b3", "#b4bcc8", "#7d8899", "#c7cdd6"];

// Arrondi lisible : pas de decimale a partir de 100, une seule en dessous.
export function round(n: number) {
  return n.toLocaleString("fr-FR", { maximumFractionDigits: Math.abs(n) >= 100 ? 0 : 1 });
}

const nf = (n: number | null | undefined, unit = "") => (n === null || n === undefined ? "Aucune donnée" : `${round(n)}${unit ? ` ${unit}` : ""}`);

// Graduations « rondes » (1, 2, 2,5, 5 x 10^n) entre 0 et le maximum.
function niceTicks(min: number, max: number, count = 4) {
  const span = max - min || 1;
  const raw = span / count;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw) || raw;
  const start = Math.floor(min / step) * step;
  const ticks = [];
  for (let v = start; v <= max + step * 0.001; v += step) ticks.push(Math.round(v * 1000) / 1000);
  if (ticks[ticks.length - 1] < max) ticks.push(ticks[ticks.length - 1] + step);
  return ticks;
}

const total = (s: Series) => s.points.reduce((a, p) => a + (p.y || 0), 0);
const defined = (s: Series) => s.points.filter((p): p is { x: string; y: number } => p.y !== null);

// Serie mise en avant : la plus lourde pour une somme, la derniere valeur la plus haute pour une moyenne.
function highlightIndex(series: Series[], aggregate: string) {
  let best = series.findIndex((s) => !s.target);
  if (best < 0) return 0;
  series.forEach((s, i) => {
    if (s.target) return;
    const score = aggregate === "sum" ? total(s) : defined(s).at(-1)?.y ?? -Infinity;
    const bestScore = aggregate === "sum" ? total(series[best]) : defined(series[best]).at(-1)?.y ?? -Infinity;
    if (score > bestScore) best = i;
  });
  return best;
}

// Reponse a la question du graphique, tiree des valeurs affichees (rien d'invente).
export function answer(detail: Detail): string | null {
  if (detail.kind === "tabs") return null;
  if (detail.kind === "line") {
    const series = detail.series.filter((s) => defined(s).length);
    if (!series.length) return null;
    const unit = detail.unit;
    const real = series.filter((s) => !s.target);
    const target = series.find((s) => s.target);
    if (target && real.length === 1) {
      // Reel contre cible : total des periodes qui ont une cible, et l'ecart.
      const withTarget = target.points.map((p, i) => (p.y === null ? null : i)).filter((i): i is number => i !== null);
      if (!withTarget.length) return `Pas de cible sur ces périodes, réel ${nf(total(real[0]), unit)}`;
      const r = withTarget.reduce((a, i) => a + (real[0].points[i]?.y || 0), 0);
      const t = withTarget.reduce((a, i) => a + (target.points[i].y || 0), 0);
      const pct = t ? Math.round((r * 100) / t) : null;
      return `Réel ${nf(r, unit)} pour une cible de ${nf(t, unit)}${pct !== null ? `, soit ${pct} % de la cible` : ""}`;
    }
    if (detail.aggregate === "cumul") {
      const ends = series.map((s) => ({ s, last: defined(s).at(-1)! })).sort((a, b) => b.last.y - a.last.y);
      const top = ends[0];
      return `Campagne ${top.s.name} : ${nf(top.last.y, unit)} cumulés en ${top.last.x}`;
    }
    const agg = detail.aggregate || (unit === "kg" ? "sum" : "mean");
    if (agg === "sum") {
      const sum = series.reduce((a, s) => a + total(s), 0);
      if (series.length > 1) {
        const top = series[highlightIndex(series, "sum")];
        return `${top.name} en tête : ${nf(total(top), unit)}, soit ${Math.round((total(top) * 100) / (sum || 1))} % du total`;
      }
      const peak = defined(series[0]).reduce((a, p) => (p.y > a.y ? p : a));
      return `${nf(sum, unit)} au total, pic en ${peak.x} (${nf(peak.y, unit)})`;
    }
    if (series.length > 1) {
      const top = series[highlightIndex(series, "mean")];
      const last = defined(top).at(-1)!;
      return `${top.name} au plus haut sur la dernière période : ${nf(last.y, unit)} (${last.x})`;
    }
    const pts = defined(series[0]);
    const first = pts[0], last = pts[pts.length - 1];
    if (pts.length < 2) return `${nf(last.y, unit)} en ${last.x}`;
    const diff = last.y - first.y;
    const unitDiff = unit === "%" ? "point(s)" : unit;
    const move = Math.abs(diff) < 0.05 ? "stable" : `${diff > 0 ? "en hausse" : "en baisse"} de ${round(Math.abs(diff))} ${unitDiff}`;
    return `${nf(last.y, unit)} en ${last.x}, ${move} depuis ${first.x}`;
  }
  if (detail.kind === "bars") {
    const bars = detail.bars.filter((b) => b.value !== null);
    if (!bars.length) return null;
    const top = bars.reduce((a, b) => ((b.value || 0) > (a.value || 0) ? b : a));
    const sum = bars.reduce((a, b) => a + (b.value || 0), 0);
    if (bars.length === 1) return `${top.label} : ${nf(top.value, detail.unit)}`;
    if (detail.unit === "%" || detail.unit === "h") return `${top.label} : ${nf(top.value, detail.unit)}, la valeur la plus haute`;
    return `${top.label} en tête : ${nf(top.value, detail.unit)}, soit ${Math.round(((top.value || 0) * 100) / (sum || 1))} % du total`;
  }
  return detail.rows.length ? `${detail.rows.length} ligne(s)` : null;
}

// Tableaux -------------------------------------------------------------------------

const cellText = (c: Cell) => (c !== null && typeof c === "object" ? String(c.text) : String(c));
// Une cellule est un nombre si elle commence par un chiffre et ne contient qu'un nombre suivi d'une unite courte.
const NUMERIC = /^-?[\d   ]+([,.]\d+)?\s?(kg|g|t|%|h|j|L|unités?|lots?)?$/;
const isNumeric = (c: Cell) => typeof c === "number" || NUMERIC.test(cellText(c).trim());
const sortValue = (c: Cell): number | string => {
  if (typeof c === "number") return c;
  const t = cellText(c).trim();
  if (NUMERIC.test(t)) return Number(t.replace(/[^\d,.-]/g, "").replace(",", "."));
  return t.toLocaleLowerCase("fr");
};

export function CellView({ cell }: { cell: Cell }) {
  if (cell !== null && typeof cell === "object") return <StatusBadge status={cell.status} text={String(cell.text)} />;
  return <>{typeof cell === "number" ? cell.toLocaleString("fr-FR") : cell}</>;
}

// Tableau triable : clic sur un en-tete pour trier, fleche du sens actif. Nombres alignes a droite,
// une ligne par cellule (texte complet au survol).
export function DataTable({ columns, rows }: { columns: string[]; rows: Cell[][] }) {
  const [sort, setSort] = useState<{ col: number; dir: 1 | -1 } | null>(null);
  const numericCols = useMemo(() => columns.map((_, j) => rows.length > 0 && rows.every((r) => isNumeric(r[j]))), [columns, rows]);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    return [...rows].sort((a, b) => {
      const x = sortValue(a[sort.col]), y = sortValue(b[sort.col]);
      return (x < y ? -1 : x > y ? 1 : 0) * sort.dir;
    });
  }, [rows, sort]);
  if (!rows.length) return <p className="muted">Rien à afficher.</p>;
  return (
    <div className="table-wrap">
      <table className="detail-table">
        <thead>
          <tr>
            {columns.map((c, j) => {
              const active = sort?.col === j;
              const ariaSort = active ? (sort.dir === 1 ? "ascending" : "descending") : "none";
              return (
                <th key={c} className={numericCols[j] ? "num" : undefined} aria-sort={ariaSort}>
                  <button
                    type="button"
                    className="sort-btn"
                    onClick={() => setSort(active ? { col: j, dir: sort.dir === 1 ? -1 : 1 } : { col: j, dir: numericCols[j] ? -1 : 1 })}
                  >
                    {c}
                    <Icon name={active ? (sort.dir === 1 ? "arrow-up" : "arrow-down") : "chevrons-up-down"} size={13} />
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j} className={numericCols[j] ? "num" : "clip"} title={typeof cell === "object" ? undefined : cellText(cell)}>
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

// Courbes -----------------------------------------------------------------------------

export function LineChart({ series, unit, aggregate = "sum" }: { series: Series[]; unit: string; aggregate?: string }) {
  const labels = series[0]?.points.map((p) => p.x) || [];
  const values = series.flatMap((s) => [...s.points.map((p) => p.y), s.band?.min ?? null, s.band?.max ?? null]).filter((v): v is number => v !== null);
  if (!labels.length || !values.length) return <p className="muted">Aucune donnée sur la période.</p>;
  const longest = Math.max(...series.map((s) => s.name.length));
  const W = 900, H = 300, L = 52, T = 14, B = 34;
  // Place a droite pour ecrire le nom de chaque courbe au bout de sa ligne.
  const R = series.length > 1 ? Math.min(220, 24 + longest * 7) : 70;
  const ticks = niceTicks(Math.min(0, ...values), Math.max(...values));
  const min = ticks[0], max = ticks[ticks.length - 1] || 1;
  const x = (i: number) => L + (labels.length === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (labels.length - 1));
  const y = (v: number) => T + (H - T - B) * (1 - (v - min) / (max - min || 1));
  const every = Math.ceil(labels.length / 8);
  const hi = highlightIndex(series, aggregate);
  const color = (i: number) => (series[i].target ? "#667085" : i === hi ? HIGHLIGHT : OTHERS[(i < hi ? i : i - 1) % OTHERS.length]);
  // Etiquettes au bout des lignes, ecartees si elles se chevauchent.
  const ends = series
    .map((s, i) => {
      const pts = s.points.map((p, k) => ({ ...p, k })).filter((p) => p.y !== null);
      const last = pts[pts.length - 1];
      return last ? { i, name: s.name, value: last.y as number, cx: x(last.k), cy: y(last.y as number), ly: y(last.y as number) } : null;
    })
    .filter((e): e is NonNullable<typeof e> => e !== null)
    .sort((a, b) => a.cy - b.cy);
  for (let k = 1; k < ends.length; k++) if (ends[k].ly - ends[k - 1].ly < 16) ends[k].ly = ends[k - 1].ly + 16;
  const single = series.length === 1;
  const plain = (si: number) => single && aggregate === "sum" && !series[si].target;
  return (
    <figure style={{ margin: 0 }}>
      <svg className="chart-svg" viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`Courbe en ${unit}`} style={{ maxHeight: 340 }}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R + 10} y1={y(t)} y2={y(t)} stroke="#eef0f3" />
            <text x={L - 8} y={y(t) + 4} textAnchor="end" fontSize="12" fill="#667085">
              {round(t)}
            </text>
          </g>
        ))}
        {series.map((s, i) =>
          s.band ? (
            <rect key={`band-${s.name}`} x={L} width={W - L - R} y={y(s.band.max)} height={Math.max(1, y(s.band.min) - y(s.band.max))} fill={color(i)} opacity={0.08}>
              <title>{`${s.name} : fourchette ${nf(s.band.min)} à ${nf(s.band.max, unit)}`}</title>
            </rect>
          ) : null,
        )}
        {labels.map((lab, i) =>
          i % every === 0 || i === labels.length - 1 ? (
            <text key={lab} x={x(i)} y={H - 10} textAnchor="middle" fontSize="12" fill="#667085">
              {lab}
            </text>
          ) : null,
        )}
        {/* Courbes grises d'abord, la courbe mise en avant par-dessus. */}
        {[...series.keys()]
          .sort((a, b) => (a === hi ? 1 : b === hi ? -1 : 0))
          .map((si) => {
            const s = series[si];
            // Une periode sans valeur coupe la ligne (pas d'invention entre deux mesures).
            const segments: { k: number; y: number }[][] = [];
            let current: { k: number; y: number }[] = [];
            s.points.forEach((p, k) => {
              if (p.y === null) {
                if (current.length) segments.push(current);
                current = [];
              } else current.push({ k, y: p.y });
            });
            if (current.length) segments.push(current);
            const c = color(si);
            return (
              <g key={s.name}>
                {plain(si) &&
                  segments.map((seg, k) =>
                    seg.length > 1 ? (
                      <path key={`a${k}`} d={`M${x(seg[0].k)},${y(min)}${seg.map((p) => `L${x(p.k)},${y(p.y)}`).join("")}L${x(seg[seg.length - 1].k)},${y(min)}Z`} fill={c} opacity={0.08} />
                    ) : null,
                  )}
                {segments.map((seg, k) => (
                  <path key={k} d={seg.map((p, n) => `${n ? "L" : "M"}${x(p.k)},${y(p.y)}`).join("")} fill="none" stroke={c} strokeWidth={si === hi ? 2.5 : 1.75} strokeDasharray={s.target ? "6 5" : undefined} strokeLinejoin="round" strokeLinecap="round" />
                ))}
                {s.points.map((p, k) =>
                  p.y === null ? null : (
                    <circle key={k} cx={x(k)} cy={y(p.y)} r={10} fill="transparent">
                      <title>{`${s.name}, ${p.x} : ${nf(p.y, unit)}`}</title>
                    </circle>
                  ),
                )}
              </g>
            );
          })}
        {ends.map((e) => (
          <g key={e.name}>
            <circle cx={e.cx} cy={e.cy} r={4} fill={color(e.i)} stroke="#fff" strokeWidth={2} />
            <text x={e.cx + 10} y={e.ly + 4} fontSize="12" fontWeight={e.i === hi ? 650 : 500} fill={e.i === hi ? HIGHLIGHT : "#475467"}>
              {single ? nf(e.value, unit) : e.name}
            </text>
          </g>
        ))}
      </svg>
      <details>
        <summary className="muted">Voir les valeurs en tableau</summary>
        <DataTable
          columns={["Période", ...series.map((s) => `${s.name} (${unit})`)]}
          rows={labels.map((lab, i) => [lab, ...series.map((s) => nf(s.points[i]?.y))])}
        />
      </details>
    </figure>
  );
}

// Barres : la plus grande en couleur, les autres en gris. Avec un etat : jaune ou rouge en couleur, vert en gris.
// l'icone et le mot de l'etat restent sur chaque barre.
export function Bars({ bars, unit }: { bars: Bar[]; unit: string }) {
  if (!bars.length) return <p className="muted">Aucune donnée.</p>;
  const max = Math.max(...bars.map((b) => b.value || 0)) || 1;
  const top = bars.reduce((a, b) => ((b.value || 0) > (a.value || 0) ? b : a));
  return (
    <div className="bars">
      {bars.map((b) => {
        // Seuls les etats a surveiller ou non OK gardent leur couleur : le reste en gris pour faire ressortir le probleme.
        const alert = b.status === "warn" || b.status === "bad";
        const color = alert ? STATUS_META[b.status!].border : b.status ? "#d0d5dd" : b === top ? HIGHLIGHT : "#d0d5dd";
        return (
          <div key={b.label} className="bar-row">
            <span>{b.label}</span>
            <span className="bar-track" title={`${b.label} : ${nf(b.value, unit)}`}>
              <span className="bar-fill" style={{ width: `${Math.max(1, ((b.value || 0) * 100) / max)}%`, background: color }} />
              <span className="bar-value">
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

// Onglets (jour, semaine, mois, saison) : un bouton par vue, le contenu de la vue choisie dessous.
function Tabs({ detail }: { detail: Extract<Detail, { kind: "tabs" }> }) {
  const [active, setActive] = useState(detail.tabs.length > 2 ? 2 : 0);
  const current = detail.tabs[active];
  return (
    <section className="detail-tabs">
      <h3 className="detail-answer">{detail.title}</h3>
      <div className="tab-row" role="tablist" aria-label={detail.title}>
        {detail.tabs.map((t, i) => (
          <button key={t.label} type="button" role="tab" aria-selected={i === active} className={i === active ? "tab active" : "tab"} onClick={() => setActive(i)}>
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" aria-label={current.label}>
        {current.details.length ? current.details.map((d, i) => <DetailView key={`${current.label}-${i}`} detail={d} />) : <p className="muted">Rien à afficher pour cette vue.</p>}
      </div>
    </section>
  );
}

export function DetailView({ detail }: { detail: Detail }) {
  if (detail.kind === "tabs") return <Tabs detail={detail} />;
  const text = detail.kind === "table" ? null : answer(detail);
  return (
    <section className="detail-block">
      {text ? (
        <>
          <h3 className="detail-answer">{text}</h3>
          <p className="detail-question">{detail.title}</p>
        </>
      ) : (
        <h3 className="detail-answer">{detail.title}</h3>
      )}
      {detail.kind === "line" && <LineChart series={detail.series} unit={detail.unit} aggregate={detail.aggregate} />}
      {detail.kind === "bars" && <Bars bars={detail.bars} unit={detail.unit} />}
      {detail.kind === "table" && <DataTable columns={detail.columns} rows={detail.rows} />}
    </section>
  );
}

// Petite courbe dans la tuile : la serie mise en avant de la premiere courbe du detail, avec un point sur la derniere valeur.
export function Sparkline({ series, aggregate = "sum" }: { series: Series[]; aggregate?: string }) {
  const s = series[highlightIndex(series, aggregate)];
  const pts = s?.points || [];
  const vals = pts.map((p) => p.y).filter((v): v is number => v !== null);
  if (vals.length < 2) return null;
  const W = 240, H = 40, P = 4;
  const max = Math.max(...vals), min = Math.min(0, ...vals);
  const xy = pts.map((p, i) => (p.y === null ? null : [(i * (W - 2 * P)) / (pts.length - 1) + P, H - P - ((p.y - min) * (H - 2 * P)) / (max - min || 1)]));
  const known = xy.filter((c): c is number[] => c !== null);
  const d = known.map((c, i) => `${i ? "L" : "M"}${c[0]},${c[1]}`).join("");
  const last = known[known.length - 1];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" aria-hidden="true" style={{ overflow: "visible", display: "block" }}>
      {aggregate === "sum" && <path d={`${d}L${last[0]},${H - P}L${known[0][0]},${H - P}Z`} fill={HIGHLIGHT} opacity={0.08} />}
      <path d={d} fill="none" stroke={HIGHLIGHT} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={last[0]} cy={last[1]} r={3} fill={HIGHLIGHT} />
    </svg>
  );
}
