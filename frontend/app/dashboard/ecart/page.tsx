"use client";

// Expliquer l'ecart a la cible, en trois clics : produit, puis equipement, puis arret (et le lot en cours).
// Les pertes dues aux arrets sont une ESTIMATION (heures d'arret x kilos par heure de l'equipement), marquee comme
// telle. Ce que les arrets declares n'expliquent pas reste « écart non expliqué » : rien n'est invente pour le combler.
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useSession } from "@/components/AppShell";
import { Detail, DetailView, DataTable, round } from "@/components/Charts";
import { errorText, unitLabel } from "@/components/Codes";
import { Icon } from "@/components/Icon";
import { Status, StatusBadge } from "@/components/Status";
import { api } from "@/lib/api";

type Period = { code: string; label: string };
type ProductRow = {
  article_id: string;
  label: string;
  article_name: string;
  unit: string;
  target: number | null;
  real: number | null;
  gap: number | null;
  attainment: number | null;
  status: Status;
  stop_loss: number | null;
  top_cause: string | null;
};
type EquipmentRow = {
  id: string;
  code: string;
  name: string;
  site: string | null;
  produced: number | null;
  run_hours: number | null;
  rate: number | null;
  unplanned_hours: number | null;
  planned_hours: number | null;
  stops: number;
  stop_loss: number | null;
  ongoing: boolean;
};
type StopRow = {
  id: string;
  started_at: string;
  ended_at: string | null;
  ongoing: boolean;
  duration_hours: number;
  cause_code: string;
  cause_label: string;
  planned: boolean;
  lots: string[];
  stop_loss: number | null;
  declared_by: string | null;
};
type Base = { period: string; periods: Period[]; from: string; to: string; estimate_note: string };
type Level1 = Base & { products: ProductRow[]; biggest_gap: string | null; message: string };
type Level2 = Base & { product: ProductRow; equipment: EquipmentRow[]; detail: Detail[]; planned_note: string; unequipped: number | null };
type Level3 = Base & {
  product: ProductRow;
  equipment: { id: string; code: string; name: string; site: string | null; rate: number | null };
  stops: StopRow[];
  detail: Detail[];
  planned_note: string;
  stops_href: string;
};

const n = (v: number | null | undefined, unit = "") => (v === null || v === undefined ? "Aucune donnée" : `${round(v)}${unit ? ` ${unit}` : ""}`);
const signed = (v: number | null, unit: string) => (v === null ? "Pas de cible" : `${v > 0 ? "+" : ""}${n(v, unit)}`);
const when = (iso: string) => new Date(iso).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
const href = (params: Record<string, string | undefined>) =>
  `/dashboard/ecart?${new URLSearchParams(Object.entries(params).filter((e): e is [string, string] => !!e[1])).toString()}`;

function Summary({ p }: { p: ProductRow }) {
  const unit = unitLabel(p.unit, 2);
  return (
    <section className="card overlay-summary">
      <p style={{ margin: 0, display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
        <strong style={{ fontSize: "1.1em" }}>{p.label}</strong>
        <StatusBadge status={p.status} text={p.attainment === null ? "Pas de cible" : `${round(p.attainment)} % de la cible`} />
      </p>
      <p style={{ margin: "8px 0 0" }}>
        Cible à date {n(p.target, unit)} · Réel {n(p.real, unit)} · Écart <strong>{signed(p.gap, unit)}</strong>
        {p.stop_loss ? ` · Perdu par arrêts non planifiés : environ ${n(p.stop_loss, unit)} (estimation)` : ""}
      </p>
    </section>
  );
}

function Products({ data }: { data: Level1 }) {
  if (!data.products.length) return <p className="notice">{data.message}</p>;
  return (
    <>
      <p className="muted">Le produit le plus en retard d&apos;abord. Cliquez sur un produit pour voir d&apos;où vient son écart.</p>
      <div className="gap-cards">
        {data.products.map((p) => {
          const unit = unitLabel(p.unit, 2);
          return (
            <Link key={p.article_id} href={href({ period: data.period, article: p.article_id })} className="gap-card">
              <span style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                <strong>{p.label}</strong>
                <StatusBadge status={p.status} text={p.attainment === null ? "Pas de cible" : `${round(p.attainment)} %`} />
              </span>
              <span>
                Écart <strong>{signed(p.gap, unit)}</strong> (cible {n(p.target, unit)}, réel {n(p.real, unit)})
              </span>
              <span className="muted">
                {p.stop_loss ? `Arrêts : environ ${n(p.stop_loss, unit)} perdus (estimation)` : "Aucune perte par arrêt déclarée"}
                {p.top_cause ? `, surtout ${p.top_cause.toLowerCase()}` : ""}
              </span>
              {p.article_id === data.biggest_gap && <span className="muted">Le plus grand retard</span>}
            </Link>
          );
        })}
      </div>
    </>
  );
}

function Product({ data }: { data: Level2 }) {
  const unit = unitLabel(data.product.unit, 2);
  return (
    <>
      <Summary p={data.product} />
      {data.detail.map((d, i) => (
        <DetailView key={i} detail={d} />
      ))}
      <section className="detail-block">
        <h3 className="detail-answer">Équipements qui ont produit {data.product.label.toLowerCase()} sur la période</h3>
        <p className="detail-question">
          Cliquez sur un équipement pour voir sa frise et ses arrêts. {data.planned_note}
          {data.unequipped ? ` ${n(data.unequipped, unit)} déclarés sans équipement ne sont rattachés à aucun.` : ""}
        </p>
        <DataTable
          columns={["Équipement", "Site", "Produit", "Heures de marche", "Kilos par heure", "Arrêts non planifiés", "Arrêts planifiés", "Perte estimée"]}
          rows={data.equipment.map((e) => [
            `${e.code} ${e.name}${e.ongoing ? " (arrêt en cours)" : ""}`,
            e.site || "Aucun",
            n(e.produced, unit),
            n(e.run_hours, "h"),
            e.rate === null ? "Aucune donnée" : n(e.rate, unit),
            n(e.unplanned_hours, "h"),
            n(e.planned_hours, "h"),
            e.stop_loss ? { text: n(e.stop_loss, unit), status: "bad" } : n(0, unit),
          ])}
        />
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 10 }}>
          {data.equipment.map((e) => (
            <Link key={e.id} href={href({ period: data.period, article: data.product.article_id, equipment: e.id })} className="btn-link">
              <Icon name="search" size={16} />
              {e.code} : frise et arrêts
            </Link>
          ))}
        </div>
      </section>
      <p className="muted">{data.estimate_note}</p>
    </>
  );
}

function Equipment({ data }: { data: Level3 }) {
  const unit = unitLabel(data.product.unit, 2);
  return (
    <>
      <Summary p={data.product} />
      <p>
        <strong>
          {data.equipment.code} {data.equipment.name}
        </strong>
        {data.equipment.site ? `, ${data.equipment.site}` : ""} · {data.equipment.rate === null ? "pas d'heure de marche déclarée" : `${n(data.equipment.rate, unit)} par heure de marche`}
      </p>
      {data.detail.map((d, i) => (
        <DetailView key={i} detail={d} />
      ))}
      <section className="detail-block">
        <h3 className="detail-answer">
          {data.stops.length} arrêt(s) sur la période, avec le lot en cours sur l&apos;équipement
        </h3>
        <p className="detail-question">{data.planned_note}</p>
        <DataTable
          columns={["Début", "Fin", "Durée", "Cause", "Type", "Lot en cours", "Perte estimée", "Déclaré par"]}
          rows={data.stops.map((s) => [
            when(s.started_at),
            s.ongoing ? { text: "En cours", status: "warn" } : s.ended_at ? when(s.ended_at) : "",
            n(s.duration_hours, "h"),
            s.cause_label,
            s.planned ? "Planifié" : { text: "Non planifié", status: "bad" },
            s.lots.length ? s.lots.join(", ") : "Aucun lot en cours",
            s.planned ? "Non comptée" : n(s.stop_loss, unit),
            s.declared_by || "Inconnu",
          ])}
        />
        <p style={{ marginTop: 10 }}>
          <Link href={data.stops_href} className="btn-link">
            <Icon name="circle-pause" size={16} />
            Ouvrir ces arrêts dans l&apos;écran Arrêts de ligne
          </Link>
        </p>
      </section>
      <p className="muted">{data.estimate_note}</p>
    </>
  );
}

function GapView() {
  const { me } = useSession();
  const params = useSearchParams();
  const period = params.get("period") || "mois";
  const article = params.get("article") || undefined;
  const equipment = params.get("equipment") || undefined;
  const [data, setData] = useState<Level1 | Level2 | Level3 | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!me) return;
    const url = article ? (equipment ? `dashboard/gap/${article}/equipment/${equipment}/` : `dashboard/gap/${article}/`) : "dashboard/gap/";
    setData(null);
    api<Level1 | Level2 | Level3>(`${url}?period=${period}`)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(errorText(e)));
  }, [me, period, article, equipment]);

  if (!me) return null;
  const product = data && "product" in data ? data.product : null;
  const equipmentInfo = data && "stops" in data ? data.equipment : null;
  return (
    <main>
      <nav className="crumbs" aria-label="Fil d'Ariane">
        <Link href="/dashboard">Tableau de bord</Link>
        <Icon name="move-right" size={14} />
        {article ? <Link href={href({ period })}>Écart par produit</Link> : <span>Écart par produit</span>}
        {product && (
          <>
            <Icon name="move-right" size={14} />
            {equipment ? <Link href={href({ period, article })}>{product.label}</Link> : <span>{product.label}</span>}
          </>
        )}
        {equipmentInfo && (
          <>
            <Icon name="move-right" size={14} />
            <span>{equipmentInfo.code}</span>
          </>
        )}
      </nav>
      <div className="dash-head">
        <h1>D&apos;où vient l&apos;écart à la cible ?</h1>
        {data && (
          <div className="tab-row" role="tablist" aria-label="Période">
            {data.periods.map((p) => (
              <Link key={p.code} role="tab" aria-selected={p.code === period} className={p.code === period ? "tab active" : "tab"} href={href({ period: p.code, article, equipment })}>
                {p.label}
              </Link>
            ))}
          </div>
        )}
      </div>
      {error && <p role="alert">{error}</p>}
      {!data && !error && <p>Chargement...</p>}
      {data && "products" in data && <Products data={data} />}
      {data && "equipment" in data && !("stops" in data) && <Product data={data as Level2} />}
      {data && "stops" in data && <Equipment data={data as Level3} />}
    </main>
  );
}

export default function GapPage() {
  return (
    <Suspense fallback={<p>Chargement...</p>}>
      <GapView />
    </Suspense>
  );
}
