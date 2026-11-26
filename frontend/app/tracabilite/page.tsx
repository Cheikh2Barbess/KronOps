"use client";

// Recherche de tracabilite (US-14 aval, US-15 amont).
// Aval : d'un lot fournisseur vers les lots produits et les clients livres. Amont : d'un lot fini vers les matieres.
import { FormEvent, useState } from "react";
import { api, ApiError } from "@/lib/api";

type Lot = {
  id: string;
  code: string;
  article_code: string;
  article_name: string;
  base_unit: string;
  supplier_name: string | null;
  supplier_lot_code: string;
  date_type: string;
  expiry_date: string | null;
  status: string;
  balance: string;
  expired: boolean;
  depth?: number;
};
type Shipment = {
  movement_id: string;
  lot_code: string;
  customer_name: string;
  customer_address: string;
  customer_phone: string;
  customer_email: string;
  quantity: string;
  occurred_at: string;
};
type Result = { origins: Lot[]; lots: Lot[]; shipments?: Shipment[] };

const STATUS: Record<string, string> = { disponible: "Disponible", bloque: "Bloqué", detruit: "Détruit" };
const fmt = (n: string) => Number(n).toLocaleString("fr-FR", { maximumFractionDigits: 3 });

function LotTable({ lots }: { lots: Lot[] }) {
  return (
    <table cellPadding={4} style={{ borderCollapse: "collapse", width: "100%" }}>
      <thead>
        <tr style={{ textAlign: "left" }}>
          <th>Lot</th>
          <th>Article</th>
          <th>Fournisseur</th>
          <th>Lot fournisseur</th>
          <th>DLC / DDM</th>
          <th>Statut</th>
          <th>En stock</th>
        </tr>
      </thead>
      <tbody>
        {lots.map((l) => (
          <tr key={l.id} style={{ borderTop: "1px solid #ddd" }}>
            <td>{l.code}</td>
            <td>
              {l.article_code} {l.article_name}
            </td>
            <td>{l.supplier_name || ""}</td>
            <td>{l.supplier_lot_code}</td>
            <td>
              {l.expiry_date ? `${l.date_type.toUpperCase()} ${new Date(l.expiry_date).toLocaleDateString("fr-FR")}` : ""}
              {l.expired ? " (périmé)" : ""}
            </td>
            <td>{STATUS[l.status] || l.status}</td>
            <td>
              {fmt(l.balance)} {l.base_unit}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function Tracabilite() {
  const [result, setResult] = useState<Result | null>(null);
  const [direction, setDirection] = useState<"downstream" | "upstream">("downstream");
  const [message, setMessage] = useState<string | null>(null);

  async function onSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const dir = form.get("direction") === "upstream" ? "upstream" : "downstream";
    const search = String(form.get("search") || "").trim();
    setMessage(null);
    setResult(null);
    try {
      const data = await api<Result>(`traceability/${dir}/?search=${encodeURIComponent(search)}`);
      setDirection(dir);
      setResult(data);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setMessage(`Aucun lot avec le code « ${search} ».`);
      else if (e instanceof ApiError && e.status === 403)
        setMessage("Connectez-vous, ou votre rôle n'a pas accès à la recherche.");
      else setMessage("Erreur pendant la recherche.");
    }
  }

  return (
    <main>
      <p>
        <a href="/">Accueil</a>
      </p>
      <h1>Traçabilité</h1>
      <form onSubmit={onSearch} style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
        <input name="search" placeholder="Code lot interne ou n° de lot fournisseur" required style={{ minWidth: 300 }} />
        <label>
          <input type="radio" name="direction" value="downstream" defaultChecked /> Aval (où est parti ce lot ?)
        </label>
        <label>
          <input type="radio" name="direction" value="upstream" /> Amont (de quoi est fait ce lot ?)
        </label>
        <button type="submit">Rechercher</button>
      </form>
      {message && <p role="alert">{message}</p>}

      {result && (
        <>
          <h2>Lot(s) recherché(s)</h2>
          <LotTable lots={result.origins} />

          <h2>{direction === "downstream" ? "Lots produits avec ce lot" : "Lots de matières utilisés"}</h2>
          {result.lots.length ? <LotTable lots={result.lots} /> : <p>Aucun.</p>}

          {direction === "downstream" && (
            <>
              <h2>Clients livrés</h2>
              {result.shipments && result.shipments.length ? (
                <table cellPadding={4} style={{ borderCollapse: "collapse", width: "100%" }}>
                  <thead>
                    <tr style={{ textAlign: "left" }}>
                      <th>Client</th>
                      <th>Adresse</th>
                      <th>Contact</th>
                      <th>Lot</th>
                      <th>Quantité</th>
                      <th>Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.shipments.map((s) => (
                      <tr key={s.movement_id} style={{ borderTop: "1px solid #ddd" }}>
                        <td>{s.customer_name}</td>
                        <td>{s.customer_address}</td>
                        <td>{[s.customer_phone, s.customer_email].filter(Boolean).join(" · ")}</td>
                        <td>{s.lot_code}</td>
                        <td>{fmt(s.quantity)}</td>
                        <td>{new Date(s.occurred_at).toLocaleDateString("fr-FR")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p>Aucune expédition.</p>
              )}
            </>
          )}
        </>
      )}
    </main>
  );
}
