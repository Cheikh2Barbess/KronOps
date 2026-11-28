"use client";

// Rapport de rappel, imprimable. Point de depart : un carton, une palette (code de lot) ou un conteneur.
// 1. Contenu : parcelles, producteurs, etapes. 2. Perimetre prudent : tout ce qui vient des memes matieres.
// 3. Ou c'est : stock a bloquer, expeditions (client, conteneur, plomb, certificat d'inspection).
import { FormEvent, useState } from "react";
import { OrganicBadge, day, errorText, when, withUnit } from "@/components/Codes";
import { Run, YieldCell } from "@/components/Runs";
import { api, ApiError } from "@/lib/api";

type Check = { result: string; checked_at: string; moisture_pct: string | null };
type Lot = {
  id: string;
  code: string;
  article_code: string;
  article_name: string;
  article_type: string;
  base_unit: string;
  supplier_name: string | null;
  parcel_code: string | null;
  parcel_locality: string | null;
  organic_status: string;
  status: string;
  balance: string;
  site_name: string | null;
  depth?: number;
  received_quantity?: string | null;
  received_at?: string | null;
  last_quality_check: Check | null;
};
type Shipment = {
  movement_id: string;
  lot_code: string;
  base_unit: string;
  quantity: string;
  occurred_at: string;
  customer_name: string | null;
  customer_address: string | null;
  customer_city: string | null;
  customer_phone: string | null;
  customer_email: string | null;
  container_number: string;
  seal_number: string;
  export_document_ref: string;
  bill_of_lading: string;
};
type Report = {
  search: string;
  container: string | null;
  origins: Lot[];
  contents: Lot[];
  roots: Lot[];
  affected: Lot[];
  in_stock: Lot[];
  runs: Run[];
  shipments: Shipment[];
  summary: { producers: number; parcels: number; affected_lots: number; lots_in_stock: number; customers: number; containers: number };
};

const STATUS: Record<string, string> = { disponible: "Disponible", bloque: "Bloqué", detruit: "Détruit" };
const table = { borderCollapse: "collapse" as const, width: "100%" };

function QC({ check }: { check: Check | null }) {
  if (!check) return <span style={{ color: "#8a5a00" }}>aucun contrôle</span>;
  return (
    <span style={{ color: check.result === "conforme" ? "#1b5e20" : "#b00020" }}>
      {check.result === "conforme" ? "Conforme" : "Non conforme"} le {day(check.checked_at)}
    </span>
  );
}

function LotRows({ lots, stock = false }: { lots: Lot[]; stock?: boolean }) {
  return (
    <table cellPadding={4} style={table}>
      <thead>
        <tr style={{ textAlign: "left" }}>
          <th>Lot</th>
          <th>Article</th>
          <th>Statut bio</th>
          <th>Site</th>
          <th>{stock ? "En stock" : "Statut"}</th>
          <th>Dernier contrôle qualité</th>
        </tr>
      </thead>
      <tbody>
        {lots.map((l) => (
          <tr key={l.id} style={{ borderTop: "1px solid #ddd" }}>
            <td>
              <strong>{l.code}</strong>
            </td>
            <td>
              {l.article_code} {l.article_name}
            </td>
            <td>
              <OrganicBadge status={l.organic_status} />
            </td>
            <td>{l.site_name || ""}</td>
            <td>
              {stock
                ? `${withUnit(l.balance, l.base_unit)} · ${STATUS[l.status] || l.status}`
                : Number(l.balance) === 0 && l.status !== "detruit"
                  ? "Épuisé (tout utilisé ou expédié)"
                  : `${STATUS[l.status] || l.status} · ${withUnit(l.balance, l.base_unit)} en stock`}
            </td>
            <td>{l.article_type === "matiere" || l.article_type === "emballage" ? "" : <QC check={l.last_quality_check} />}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function Rappel() {
  const [report, setReport] = useState<Report | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function onSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const search = String(new FormData(event.currentTarget).get("search") || "").trim();
    setMessage(null);
    setReport(null);
    try {
      setReport(await api<Report>(`traceability/recall/?search=${encodeURIComponent(search)}`));
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setMessage(`Aucun lot ni conteneur « ${search} ».`);
      else setMessage(errorText(e));
    }
  }

  const raw = report?.roots.filter((r) => r.article_type !== "emballage") || [];
  const packaging = report?.roots.filter((r) => r.article_type === "emballage") || [];
  return (
    <main>
      <h1>Rapport de rappel</h1>
      <form onSubmit={onSearch} className="no-print" style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        <input name="search" required placeholder="Code du carton, de la palette, ou n° de conteneur" style={{ minWidth: 340, fontSize: "1.1em" }} />
        <button type="submit">Préparer le rapport</button>
        {report && (
          <button type="button" onClick={() => window.print()}>
            Imprimer ou enregistrer en PDF
          </button>
        )}
      </form>
      {message && <p role="alert">{message}</p>}
      {report && (
        <>
          <p>
            Rapport du {when(new Date().toISOString())} pour <strong>{report.container ? `le conteneur ${report.container}` : report.search}</strong>.
          </p>
          <p style={{ fontSize: "1.1em", background: "#f3f3f3", padding: 8 }}>
            {report.summary.parcels} parcelle(s) de {report.summary.producers} producteur(s) · {report.summary.affected_lots} lot(s) dans le
            périmètre · <strong>{report.summary.lots_in_stock} lot(s) encore en stock à bloquer</strong> · {report.summary.customers}{" "}
            client(s) livré(s) · {report.summary.containers} conteneur(s)
          </p>

          <h2>1. Origine : parcelles et producteurs</h2>
          <table cellPadding={4} style={table}>
            <thead>
              <tr style={{ textAlign: "left" }}>
                <th>Lot reçu</th>
                <th>Producteur</th>
                <th>Parcelle</th>
                <th>Statut bio</th>
                <th>Reçu le</th>
                <th>Quantité reçue</th>
              </tr>
            </thead>
            <tbody>
              {raw.map((r) => (
                <tr key={r.id} style={{ borderTop: "1px solid #ddd" }}>
                  <td>
                    {r.code}
                    <br />
                    <small>{r.article_name}</small>
                  </td>
                  <td>{r.supplier_name}</td>
                  <td>
                    {r.parcel_code}
                    {r.parcel_locality ? ` · ${r.parcel_locality}` : ""}
                  </td>
                  <td>
                    <OrganicBadge status={r.organic_status} />
                  </td>
                  <td>{r.received_at ? when(r.received_at) : ""}</td>
                  <td>{r.received_quantity ? withUnit(r.received_quantity, r.base_unit) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {packaging.length > 0 && (
            <p>
              Emballages utilisés : {packaging.map((p) => `${p.code} (${p.article_name}, ${p.supplier_name || ""})`).join(", ")}.
            </p>
          )}

          <h2>2. Étapes de fabrication</h2>
          <table cellPadding={4} style={table}>
            <thead>
              <tr style={{ textAlign: "left" }}>
                <th>Fin</th>
                <th>Étape</th>
                <th>Lots consommés</th>
                <th>Lot produit</th>
                <th>Rendement</th>
              </tr>
            </thead>
            <tbody>
              {report.runs.map((r) => (
                <tr key={r.id} style={{ borderTop: "1px solid #ddd", verticalAlign: "top" }}>
                  <td>{when(r.ended_at)}</td>
                  <td>
                    {r.step_label}
                    {r.equipment_code ? ` · ${r.equipment_code}` : ""}
                    {r.site_name ? ` · ${r.site_name}` : ""}
                  </td>
                  <td>
                    {r.inputs.map((i) => (
                      <div key={i.lot_code}>
                        {i.lot_code} : {withUnit(i.quantity, i.base_unit)}
                      </div>
                    ))}
                  </td>
                  <td>
                    {r.output_lot_code} · {withUnit(r.output_quantity, r.base_unit)}
                  </td>
                  <td>
                    <YieldCell run={r} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <h2>3. Stock à bloquer</h2>
          {report.in_stock.length ? <LotRows lots={report.in_stock} stock /> : <p>Plus rien en stock.</p>}

          <h2>4. Expéditions : clients et conteneurs</h2>
          {report.shipments.length === 0 ? (
            <p>Aucune expédition.</p>
          ) : (
            <table cellPadding={4} style={table}>
              <thead>
                <tr style={{ textAlign: "left" }}>
                  <th>Date</th>
                  <th>Client</th>
                  <th>Contact</th>
                  <th>Lot</th>
                  <th>Quantité</th>
                  <th>Conteneur et plomb</th>
                  <th>Documents</th>
                </tr>
              </thead>
              <tbody>
                {report.shipments.map((s) => (
                  <tr key={s.movement_id} style={{ borderTop: "1px solid #ddd", verticalAlign: "top" }}>
                    <td>{day(s.occurred_at)}</td>
                    <td>
                      {s.customer_name}
                      <br />
                      <small>{s.customer_address}</small>
                    </td>
                    <td>{[s.customer_phone, s.customer_email].filter(Boolean).join(" · ")}</td>
                    <td>{s.lot_code}</td>
                    <td>{withUnit(s.quantity, s.base_unit)}</td>
                    <td>
                      {s.container_number}
                      {s.seal_number ? ` · plomb ${s.seal_number}` : ""}
                    </td>
                    <td>
                      {s.export_document_ref && <div>COI {s.export_document_ref}</div>}
                      {s.bill_of_lading && <div>BL {s.bill_of_lading}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <h2>5. Tous les lots du périmètre</h2>
          <p style={{ color: "#555" }}>
            Le périmètre prudent comprend tout ce qui a été fabriqué avec les mêmes lots reçus, même dans un autre séchoir. Les
            emballages ne l&apos;élargissent pas.
          </p>
          <LotRows lots={report.affected} />
        </>
      )}
    </main>
  );
}
