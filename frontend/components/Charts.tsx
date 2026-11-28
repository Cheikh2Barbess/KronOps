"use client";

// Courbes, barres et tableaux du tableau de bord, en SVG et HTML simples (aucune bibliotheque ajoutee).
// Regles de lecture :
// - un graphique = une question. Le titre affiche la reponse (calculee des donnees), la question vient dessous ;
// - une seule couleur mise en avant (la serie la plus importante), les autres en gris ;
// - le nom de chaque courbe est ecrit au bout de la ligne, pas dans une legende a part ;
// - chiffres arrondis, sans decimale au-dela de 100.
// Couleurs d'etat (vert, jaune, rouge) : toujours avec icone et mot (components/Status.tsx).
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { Icon } from "@/components/Icon";
import { Status, StatusBadge, StatusIcon, STATUS_META } from "@/components/Status";

export type Cell = string | number | { text: string | number; status: Status };
export type Point = { x: string; y: number | null };
// `target` : serie de cible (Sollwert), dessinee en pointilles gris, jamais mise en avant.
export type Series = { name: string; points: Point[]; band?: { min: number; max: number }; target?: boolean };
// href : la barre ouvre la liste des evenements qu'elle resume (ex. les arrets de cette cause).
export type Bar = { label: string; value: number | null; status?: Status; href?: string };
// Cascade de l'ecart : les totaux partent de zero, les autres pas montent ou descendent depuis le total courant.
export type WaterfallStep = { code: string; label: string; value: number | null; total: boolean; estimate: boolean; note: string };
// Frise : une ligne par equipement, des plages de temps colorees par nature (marche, arret planifie ou non).
export type TimelineItem = { start: string; end: string; kind: string; label: string; href?: string };
// aggregate : "sum" (kilos par periode), "mean" (pourcentages, heures), "cumul" (total qui s'accumule).
export type Detail =
  | { kind: "line"; title: string; unit: string; series: Series[]; aggregate?: "sum" | "mean" | "cumul" }
  | { kind: "bars"; title: string; unit: string; bars: Bar[] }
  | { kind: "table"; title: string; columns: string[]; rows: Cell[][] }
  | { kind: "tabs"; title: string; tabs: { label: string; details: Detail[] }[] }
  | { kind: "waterfall"; title: string; unit: string; steps: WaterfallStep[] }
  | { kind: "timeline"; title: string; start: string; end: string; lanes: { label: string; items: TimelineItem[] }[]; legend: Record<string, string> };

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
  if (detail.kind === "waterfall") {
    const get = (code: string) => detail.steps.find((s) => s.code === code)?.value ?? null;
    const target = get("target"), real = get("real"), loss = get("stop_loss");
    if (target === null || real === null) return null;
    const gap = real - target;
    const lost = Math.abs(loss || 0);
    if (gap >= 0) return `Au-dessus de la cible de ${nf(gap, detail.unit)}${lost ? `, malgré environ ${nf(lost, detail.unit)} perdus par arrêts` : ""}`;
    if (!lost) return `Écart ${nf(gap, detail.unit)} : aucun arrêt déclaré ne l'explique`;
    if (lost >= Math.abs(gap)) return `Écart ${nf(gap, detail.unit)} : les arrêts déclarés (environ ${nf(lost, detail.unit)} perdus) suffisent à l'expliquer`;
    return `Écart ${nf(gap, detail.unit)} : les arrêts déclarés en expliquent environ ${Math.round((lost * 100) / Math.abs(gap))} %`;
  }
  if (detail.kind === "timeline") {
    const items = detail.lanes.flatMap((l) => l.items.filter((i) => i.kind !== "run"));
    if (!items.length) return "Aucun arrêt sur la frise";
    const ongoing = items.filter((i) => i.kind === "ongoing").length;
    return `${items.length} arrêt(s) sur la frise${ongoing ? `, dont ${ongoing} en cours` : ""}`;
  }
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
            <span>{b.href ? <Link href={b.href}>{b.label}</Link> : b.label}</span>
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

// Cascade : cible, pertes, ecart non explique, reel. Totaux en bleu, pertes en rouge (icone et mot dans le tableau),
// gains en vert. Une estimation est hachuree et marquee « estimation » : elle ne passe jamais pour une mesure.
export function Waterfall({ steps, unit }: { steps: WaterfallStep[]; unit: string }) {
  const shown = steps.filter((s) => s.value !== null);
  if (!shown.length) return <p className="muted">Aucune donnée.</p>;
  let running = 0;
  const bars = shown.map((s) => {
    const v = s.value as number;
    const from = s.total ? 0 : running;
    const to = s.total ? v : running + v;
    running = to;
    return { ...s, from, to };
  });
  const values = bars.flatMap((b) => [b.from, b.to, 0]);
  const ticks = niceTicks(Math.min(...values), Math.max(...values));
  const min = ticks[0], max = ticks[ticks.length - 1] || 1;
  const W = 900, H = 300, L = 60, R = 16, T = 24, B = 54;
  const slot = (W - L - R) / bars.length;
  const y = (v: number) => T + (H - T - B) * (1 - (v - min) / (max - min || 1));
  const color = (b: (typeof bars)[number]) => (b.total ? HIGHLIGHT : (b.value as number) < 0 ? STATUS_META.bad.border : STATUS_META.ok.border);
  return (
    <figure style={{ margin: 0 }}>
      <svg className="chart-svg" viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`Cascade de l'écart en ${unit}`} style={{ maxHeight: 340 }}>
        <defs>
          <pattern id="hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="8" height="8" fill="#fff" />
            <line x1="0" y1="0" x2="0" y2="8" stroke={STATUS_META.bad.border} strokeWidth="4" />
          </pattern>
        </defs>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - R} y1={y(t)} y2={y(t)} stroke={t === 0 ? "#98a2b3" : "#eef0f3"} />
            <text x={L - 8} y={y(t) + 4} textAnchor="end" fontSize="12" fill="#667085">
              {round(t)}
            </text>
          </g>
        ))}
        {bars.map((b, i) => {
          const top = y(Math.max(b.from, b.to)), height = Math.max(2, Math.abs(y(b.from) - y(b.to)));
          const cx = L + slot * i + slot / 2, w = Math.min(90, slot * 0.6);
          return (
            <g key={b.code}>
              <rect x={cx - w / 2} y={top} width={w} height={height} rx={3} fill={b.estimate ? "url(#hatch)" : color(b)} stroke={color(b)} strokeWidth={b.estimate ? 2 : 0}>
                <title>{`${b.label} : ${nf(b.value, unit)}${b.estimate ? " (estimation)" : ""}. ${b.note}`}</title>
              </rect>
              <text x={cx} y={top - 6} textAnchor="middle" fontSize="12" fontWeight={b.total ? 650 : 500} fill="#344054">
                {`${!b.total && (b.value as number) > 0 ? "+" : ""}${nf(b.value, unit)}`}
              </text>
              <text x={cx} y={H - 30} textAnchor="middle" fontSize="12" fill="#475467">
                {b.label.length > 22 ? `${b.label.slice(0, 21)}…` : b.label}
              </text>
              {b.estimate && (
                <text x={cx} y={H - 14} textAnchor="middle" fontSize="11" fill={STATUS_META.bad.fg}>
                  estimation
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <DataTable
        columns={["Étape", "Valeur", "Nature", "Comment c'est calculé"]}
        rows={shown.map((s) => [
          s.label,
          s.total ? nf(s.value, unit) : { text: `${(s.value as number) > 0 ? "+" : ""}${nf(s.value, unit)}`, status: (s.value as number) < 0 ? "bad" : "ok" },
          s.total ? "Total" : s.estimate ? "Estimation" : "Calcul",
          s.note || "",
        ])}
      />
    </figure>
  );
}

const TIMELINE_COLORS: Record<string, string> = { run: "#c7d7fb", unplanned: STATUS_META.bad.border, planned: "#98a2b3", ongoing: STATUS_META.warn.border };
const dayFmt = (d: Date) => d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" });
const timeFmt = (d: Date) => d.toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

// Frise : axe du temps en jours, une ligne par equipement. Clic sur un arret : la liste des arrets correspondants.
export function Timeline({ detail }: { detail: Extract<Detail, { kind: "timeline" }> }) {
  const router = useRouter();
  const begin = new Date(detail.start).getTime(), finish = new Date(detail.end).getTime();
  if (!detail.lanes.length || finish <= begin) return <p className="muted">Rien sur la frise pour cette période.</p>;
  const W = 900, L = 150, R = 12, laneH = 30, T = 8, B = 26;
  const H = T + detail.lanes.length * laneH + B;
  const x = (t: number) => L + ((t - begin) * (W - L - R)) / (finish - begin);
  const days: number[] = [];
  const first = new Date(begin);
  first.setHours(0, 0, 0, 0);
  for (let d = first.getTime() + 86400000; d < finish; d += 86400000) days.push(d);
  const every = Math.ceil(days.length / 10) || 1;
  const kinds = Array.from(new Set(detail.lanes.flatMap((l) => l.items.map((i) => i.kind))));
  return (
    <figure style={{ margin: 0 }}>
      <svg className="chart-svg" viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={detail.title}>
        {days.map((d, i) => (
          <g key={d}>
            <line x1={x(d)} x2={x(d)} y1={T} y2={H - B} stroke="#eef0f3" />
            {i % every === 0 && (
              <text x={x(d)} y={H - 8} textAnchor="middle" fontSize="11" fill="#667085">
                {dayFmt(new Date(d))}
              </text>
            )}
          </g>
        ))}
        {detail.lanes.map((lane, li) => {
          const top = T + li * laneH;
          return (
            <g key={lane.label}>
              <text x={L - 8} y={top + laneH / 2 + 4} textAnchor="end" fontSize="12" fill="#344054">
                {lane.label.length > 20 ? `${lane.label.slice(0, 19)}…` : lane.label}
              </text>
              <line x1={L} x2={W - R} y1={top + laneH / 2} y2={top + laneH / 2} stroke="#f2f4f7" strokeWidth={laneH - 10} />
              {lane.items.map((item, k) => {
                const a = x(new Date(item.start).getTime()), b = x(new Date(item.end).getTime());
                const stopItem = item.kind !== "run";
                return (
                  <rect
                    key={k}
                    x={a}
                    width={Math.max(3, b - a)}
                    y={top + (stopItem ? 5 : 9)}
                    height={stopItem ? laneH - 10 : laneH - 18}
                    rx={2}
                    fill={TIMELINE_COLORS[item.kind] || "#98a2b3"}
                    style={item.href ? { cursor: "pointer" } : undefined}
                    onClick={item.href ? () => router.push(item.href!) : undefined}
                  >
                    <title>{`${detail.legend[item.kind] || item.kind} : ${item.label}, du ${timeFmt(new Date(item.start))} au ${timeFmt(new Date(item.end))}`}</title>
                  </rect>
                );
              })}
            </g>
          );
        })}
      </svg>
      <p className="timeline-legend">
        {kinds.map((k) => (
          <span key={k}>
            <span className="legend-swatch" style={{ background: TIMELINE_COLORS[k] || "#98a2b3" }} />
            {detail.legend[k] || k}
          </span>
        ))}
      </p>
      <details>
        <summary className="muted">Voir la frise en tableau</summary>
        <DataTable
          columns={["Équipement", "Nature", "Début", "Fin", "Détail"]}
          rows={detail.lanes.flatMap((l) =>
            l.items.map((i) => [l.label, detail.legend[i.kind] || i.kind, timeFmt(new Date(i.start)), i.kind === "ongoing" ? "En cours" : timeFmt(new Date(i.end)), i.label]),
          )}
        />
      </details>
    </figure>
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
      {detail.kind === "waterfall" && <Waterfall steps={detail.steps} unit={detail.unit} />}
      {detail.kind === "timeline" && <Timeline detail={detail} />}
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
