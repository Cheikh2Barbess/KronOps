"use client";

// Tableau de bord : ecran ouvert par defaut a la connexion. Chaque role a le sien (le serveur choisit les tuiles).
// Une tuile = un indicateur calcule a partir des saisies reelles, avec son etat vert, jaune ou rouge selon les
// seuils de l'entreprise (valeurs par defaut signalees). Un clic agrandit la tuile en plein ecran avec ses
// courbes, ses barres (goulot par etape) et le detail.
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSession } from "@/components/AppShell";
import { Detail, DetailView, Sparkline } from "@/components/Charts";
import { errorText } from "@/components/Codes";
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
};
type Dashboard = { role: string; days: number; periods: number[]; generated_at: string; tiles: Tile[] };

const PERIOD_LABELS: Record<number, string> = { 7: "7 derniers jours", 30: "30 derniers jours", 90: "3 derniers mois", 365: "12 derniers mois" };
const ROLE_TITLES: Record<string, string> = {
  admin: "Vue direction",
  lecture: "Vue direction (lecture)",
  production: "Vue production",
  qualite: "Vue qualité",
  operateur: "Vue opérateur",
};

const num = (n: number) => n.toLocaleString("fr-FR", { maximumFractionDigits: 1 });

function TileValue({ tile }: { tile: Tile }) {
  if (tile.empty || tile.value === null) return <div className="tile-value" style={{ fontSize: "1.1em", color: "#4b5563" }}>Pas encore de donnée</div>;
  return (
    <div className="tile-value">
      {num(tile.value)} <small>{tile.unit}</small>
      {tile.value_label && (
        <>
          {" "}
          <small>{tile.value_label}</small>
        </>
      )}
    </div>
  );
}

function TileCard({ tile, onOpen }: { tile: Tile; onOpen: () => void }) {
  const firstLine = tile.detail.find((d) => d.kind === "line");
  return (
    <button type="button" className="tile" onClick={onOpen} style={{ ["--tile-color" as string]: STATUS_META[tile.status].border }}
      aria-label={`${tile.title} : ${tile.status_label}. Ouvrir en plein écran`}>
      <span className="tile-title">
        <span>{tile.title}</span>
        <StatusBadge status={tile.status} text={tile.status_label} />
      </span>
      <TileValue tile={tile} />
      {tile.subtitle && <span className="tile-sub">{tile.subtitle}</span>}
      {firstLine && firstLine.kind === "line" && <Sparkline series={firstLine.series} />}
      <span className="tile-foot">{tile.scope === "now" ? "État actuel" : "Sur la période"} · cliquer pour agrandir</span>
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
      <div className="overlay-head">
        <h2 id="tile-full-title">{tile.title}</h2>
        <StatusBadge status={tile.status} text={tile.status_label} />
        <button ref={close} type="button" className="overlay-close" onClick={onClose}>
          Fermer (Échap)
        </button>
      </div>
      <TileValue tile={tile} />
      {tile.subtitle && <p className="tile-sub" style={{ fontSize: "1.05em" }}>{tile.subtitle}</p>}
      <p style={{ color: "#4b5563" }}>
        {tile.scope === "now" ? "État actuel." : `Période : ${PERIOD_LABELS[days] || `${days} jours`}.`} Source : {tile.source}
        {tile.threshold && (
          <>
            <br />
            Couleur : {thresholdText(tile.threshold)}.
          </>
        )}
      </p>
      {tile.empty ? <p>Aucune saisie sur la période : rien n&apos;est calculé tant qu&apos;il n&apos;y a pas de donnée.</p> : tile.detail.map((d, i) => <DetailView key={i} detail={d} />)}
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
        <span style={{ color: "#4b5563" }}>{ROLE_TITLES[me.role] || me.role}</span>
        <span style={{ flex: 1 }} />
        {data && (
          <label>
            Période{" "}
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
          Actualiser
        </button>
        {me.role === "admin" && <Link href="/dashboard/seuils">Régler les seuils des couleurs</Link>}
      </div>
      {error && <p role="alert">{error}</p>}
      {data && (
        <p style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", margin: "12px 0 0" }}>
          {(["bad", "warn", "ok", "info"] as Status[])
            .filter((s) => counts[s])
            .map((s) => (
              <StatusBadge key={s} status={s} text={`${counts[s]} ${STATUS_META[s].label.toLowerCase()}`} />
            ))}
          <small style={{ color: "#6b7280" }}>Calculé le {new Date(data.generated_at).toLocaleString("fr-FR")}</small>
        </p>
      )}
      {!data && !error && <p>Chargement...</p>}
      <div className="dash-grid">
        {data?.tiles.map((t) => (
          <TileCard key={t.code} tile={t} onOpen={() => setOpen(t.code)} />
        ))}
      </div>
      {tile && data && <FullScreen tile={tile} days={data.days} onClose={onClose} />}
    </main>
  );
}
