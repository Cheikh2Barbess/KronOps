"use client";

// Tableau de bord : ecran ouvert par defaut a la connexion. Chaque role a le sien (le serveur choisit les tuiles).
// Une tuile = un indicateur calcule a partir des saisies reelles, avec son etat vert, jaune ou rouge selon les
// seuils de l'entreprise (valeurs par defaut signalees). Un clic agrandit la tuile en plein ecran avec ses
// courbes, ses barres (goulot par etape) et le detail.
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "@/components/AppShell";
import { Detail, DetailView, round, Sparkline } from "@/components/Charts";
import { errorText } from "@/components/Codes";
import { Icon, IconName } from "@/components/Icon";
import { Status, StatusBadge, STATUS_META } from "@/components/Status";
import { api } from "@/lib/api";
import { Threshold, thresholdText } from "@/lib/thresholds";

type Tile = {
  code: string;
  title: string;
  value: number | null;
  value_label: string | null;
  unit: string;
  status: Status;
  status_label: string;
  subtitle: string;
  threshold: Threshold | null;
  detail: Detail[];
  empty: boolean;
  scope: "period" | "now";
  source: string;
  // Meme indicateur sur la periode juste avant (meme duree). null : pas de donnee, ou etat actuel sans historique.
  previous: number | null;
};
type Dashboard = { role: string; days: number; periods: number[]; generated_at: string; tiles: Tile[] };

const PERIOD_LABELS: Record<number, string> = { 7: "7 derniers jours", 30: "30 derniers jours", 90: "3 derniers mois", 365: "12 derniers mois" };
const PREVIOUS_LABELS: Record<number, string> = { 7: "7 jours d'avant", 30: "30 jours d'avant", 90: "3 mois d'avant", 365: "12 mois d'avant" };
const ROLE_TITLES: Record<string, string> = {
  admin: "Vue direction",
  lecture: "Vue direction (lecture)",
  production: "Vue production",
  qualite: "Vue qualité",
  operateur: "Vue opérateur",
};

// Une icone par indicateur (meme famille que le menu).
const TILE_ICONS: Record<string, IconName> = {
  received: "truck",
  produced: "factory",
  shipped: "ship",
  yields: "scale",
  qc: "clipboard-check",
  moisture: "droplets",
  blocked: "lock",
  approvals: "stamp",
  bottleneck: "hourglass",
  wip: "layers",
  stock: "boxes",
  expiry: "calendar-clock",
  organic: "leaf",
  reception_conformity: "file-check",
  late_entries: "clock",
  runs: "activity",
  my_entries: "list-checks",
  ready_without_qc: "flask-conical",
};

function TileValue({ tile }: { tile: Tile }) {
  if (tile.empty || tile.value === null) return <div className="tile-value empty">{(!tile.empty && tile.value_label) || "Pas encore de donnée"}</div>;
  return (
    <div className="tile-value">
      {round(tile.value)} <small>{tile.unit}</small>
      {tile.value_label && (
        <>
          {" "}
          <small>{tile.value_label}</small>
        </>
      )}
    </div>
  );
}

// Evolution par rapport a la periode d'avant. En pourcentage d'ecart, sauf pour un indicateur deja en %
// (ecart en points). Vert si l'evolution va dans le bon sens selon le seuil, rouge sinon, gris sans seuil.
// Toujours un mot (« en hausse », « en baisse », « stable ») en plus de la fleche.
function Trend({ tile, days }: { tile: Tile; days: number }) {
  if (tile.scope === "now") return null;
  if (tile.empty || tile.value === null) return null;
  const versus = PREVIOUS_LABELS[days] || "période d'avant";
  if (tile.previous === null || tile.previous === undefined) return <span className="trend">Pas de donnée sur les {versus}</span>;
  const points = tile.unit === "%";
  const diff = tile.value - tile.previous;
  if (!points && tile.previous === 0) return <span className="trend">Rien sur la période d&apos;avant</span>;
  const change = points ? diff : (diff * 100) / Math.abs(tile.previous);
  const stable = Math.abs(change) < (points ? 0.1 : 0.5);
  const up = change > 0;
  const better = tile.threshold ? (tile.threshold.direction === "higher" ? up : !up) : null;
  const tone = stable || better === null ? "neutral" : better ? "good" : "bad";
  const word = stable ? "stable" : up ? "en hausse" : "en baisse";
  // Ecart en % arrondi a l'unite, ecart en points a une decimale.
  const size = points ? round(Math.abs(change)) : Math.round(Math.abs(change)).toLocaleString("fr-FR");
  const amount = `${up ? "+" : "-"}${size} ${points ? "pt" : "%"}`;
  return (
    <span className="trend" title={`${word}, période d'avant : ${round(tile.previous)} ${tile.unit}`}>
      <span className={`trend-delta trend-${tone}`}>
        <Icon name={stable ? "move-right" : up ? "trending-up" : "trending-down"} size={14} />
        {stable ? "stable" : amount}
        {!stable && <span className="sr-only">{word}</span>}
      </span>
      <span>vs {versus}</span>
    </span>
  );
}

function TileCard({ tile, days, onOpen }: { tile: Tile; days: number; onOpen: () => void }) {
  const firstLine = tile.detail.find((d) => d.kind === "line");
  return (
    <button type="button" className="tile" onClick={onOpen} aria-label={`${tile.title} : ${tile.status_label}. Ouvrir en plein écran`}>
      <span className="tile-head">
        <span className="tile-icon">
          <Icon name={TILE_ICONS[tile.code] || "activity"} size={17} />
        </span>
        <StatusBadge status={tile.status} text={tile.status_label} />
      </span>
      <span className="tile-title">{tile.title}</span>
      <TileValue tile={tile} />
      <Trend tile={tile} days={days} />
      {firstLine && firstLine.kind === "line" ? (
        <Sparkline series={firstLine.series} aggregate={firstLine.aggregate} />
      ) : (
        tile.subtitle && <span className="tile-sub">{tile.subtitle}</span>
      )}
      <span className="tile-foot">
        <span>{tile.scope === "now" ? "État actuel, sans comparaison" : PERIOD_LABELS[days] || `${days} jours`}</span>
        <Icon name="maximize-2" size={14} />
      </span>
    </button>
  );
}

function FullScreen({ tile, days, onClose }: { tile: Tile; days: number; onClose: () => void }) {
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    close.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);
  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-labelledby="tile-full-title">
      <div className="overlay-inner">
        <div className="overlay-head">
          <span className="tile-icon">
            <Icon name={TILE_ICONS[tile.code] || "activity"} size={18} />
          </span>
          <h2 id="tile-full-title">{tile.title}</h2>
          <StatusBadge status={tile.status} text={tile.status_label} />
          <button ref={close} type="button" className="overlay-close" onClick={onClose}>
            <Icon name="x" size={16} />
            Fermer (Échap)
          </button>
        </div>
        <section className="card overlay-summary">
          <TileValue tile={tile} />
          <div style={{ marginTop: 8 }}>
            <Trend tile={tile} days={days} />
          </div>
          {tile.subtitle && <p style={{ margin: "12px 0 0", color: "var(--text-2)" }}>{tile.subtitle}</p>}
          <p className="overlay-meta">
            {tile.scope === "now" ? "État actuel." : `Période : ${PERIOD_LABELS[days] || `${days} jours`}.`} Source : {tile.source}
            {tile.threshold && (
              <>
                <br />
                Couleur : {thresholdText(tile.threshold)}.
              </>
            )}
          </p>
        </section>
        {tile.empty ? (
          <p className="muted">Aucune saisie sur la période : rien n&apos;est calculé tant qu&apos;il n&apos;y a pas de donnée.</p>
        ) : (
          tile.detail.map((d, i) => <DetailView key={i} detail={d} />)
        )}
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const { me } = useSession();
  const [data, setData] = useState<Dashboard | null>(null);
  const [days, setDays] = useState<number | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Dashboard>(`dashboard/${days ? `?days=${days}` : ""}`)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(errorText(e)));
  }, [days]);
  useEffect(() => {
    if (me) load();
  }, [me, load]);

  const onClose = useCallback(() => setOpen(null), []);
  if (!me) return null;
  const tile = data?.tiles.find((t) => t.code === open);
  const counts = (data?.tiles || []).reduce((acc, t) => ({ ...acc, [t.status]: (acc[t.status] || 0) + 1 }), {} as Record<string, number>);
  return (
    <main>
      <div className="dash-head">
        <h1>Tableau de bord</h1>
        <span className="dash-role">{ROLE_TITLES[me.role] || me.role}</span>
        <div className="dash-tools">
          {data && (
            <label style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
              <span className="muted">Période</span>
              <select value={data.days} onChange={(e) => setDays(Number(e.target.value))}>
                {data.periods.map((p) => (
                  <option key={p} value={p}>
                    {PERIOD_LABELS[p] || `${p} jours`}
                  </option>
                ))}
              </select>
            </label>
          )}
          <button type="button" onClick={load}>
            <Icon name="refresh-cw" size={16} />
            Actualiser
          </button>
          {me.role === "admin" && (
            <Link href="/dashboard/seuils" className="btn-link">
              <Icon name="sliders-horizontal" size={16} />
              Régler les seuils
            </Link>
          )}
        </div>
      </div>
      {error && <p role="alert">{error}</p>}
      {data && (
        <div className="dash-summary">
          {(["bad", "warn", "ok", "info"] as Status[])
            .filter((s) => counts[s])
            .map((s) => (
              <StatusBadge key={s} status={s} text={`${counts[s]} ${STATUS_META[s].label.toLowerCase()}`} />
            ))}
          <small className="muted">Calculé le {new Date(data.generated_at).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</small>
        </div>
      )}
      {!data && !error && <p>Chargement...</p>}
      <div className="dash-grid">
        {data?.tiles.map((t) => (
          <TileCard key={t.code} tile={t} days={data.days} onOpen={() => setOpen(t.code)} />
        ))}
      </div>
      {tile && data && <FullScreen tile={tile} days={data.days} onClose={onClose} />}
    </main>
  );
}
