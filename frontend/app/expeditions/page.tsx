"use client";

// Expedition : un depart vers un client (souvent un conteneur). On choisit les palettes ou cartons,
// la quantite (en cartons ou en kg), le conteneur, le plomb et le certificat d'inspection (COI TRACES).
import { FormEvent, useCallback, useEffect, useState } from "react";
import { LateEntry, Menu, ORGANIC, Option, OrganicBadge, errorText, day, lateFields, withUnit } from "@/components/Codes";
import { api } from "@/lib/api";

type Conversion = { unit_name: string; factor: string };
type Lot = {
  id: string;
  code: string;
  article_name: string;
  base_unit: string;
  organic_status: string;
  balance: string;
  site_name: string | null;
  quality_result: string | null;
  conversions: Conversion[];
};
type Options = { customers: { id: string; name: string; city: string }[]; sites: { id: string; name: string }[]; lots: Lot[]; late_reasons: Option[] };
type Shipment = {
  id: string;
  customer_name: string;
  customer_city: string;
  site_name: string | null;
  shipped_at: string;
  container_number: string;
  seal_number: string;
  export_document_ref: string;
  bill_of_lading: string;
  lines: { lot_code: string; article_name: string; base_unit: string; quantity: string; organic_status: string }[];
};
type Line = { quantity: string; unit: string };

export default function Expeditions() {
  const [options, setOptions] = useState<Options | null>(null);
  const [shipments, setShipments] = useState<Shipment[]>([]);
  const [lines, setLines] = useState<Record<string, Line>>({});
  const [coi, setCoi] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formKey, setFormKey] = useState(0);

  const load = useCallback(() => {
    api<Options>("shipments/options/").then(setOptions).catch((e) => setError(errorText(e)));
    api<Shipment[]>("shipments/").then(setShipments).catch(() => setShipments([]));
  }, []);
  useEffect(load, [load]);

  const picked = Object.entries(lines).filter(([, l]) => Number(l.quantity.replace(",", ".")) > 0);
  const lotById = Object.fromEntries((options?.lots || []).map((l) => [l.id, l]));
  const pickedLots = picked.map(([id]) => lotById[id]).filter(Boolean);
  const unchecked = pickedLots.filter((l) => l.quality_result !== "conforme");
  const bio = pickedLots.some((l) => l.organic_status === "bio" || l.organic_status === "conversion");

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    const late = lateFields(form);
    const payload: Record<string, unknown> = {
      customer: form.get("customer"),
      container_number: String(form.get("container_number") || ""),
      seal_number: String(form.get("seal_number") || ""),
      export_document_ref: coi,
      bill_of_lading: String(form.get("bill_of_lading") || ""),
      lines: picked.map(([lot, l]) => ({ lot, quantity: l.quantity.replace(",", "."), unit: l.unit })),
      ...late,
    };
    if (form.get("site")) payload.site = form.get("site");
    if (late.occurred_at) {
      payload.shipped_at = late.occurred_at;
      delete payload.occurred_at;
    }
    try {
      const s = await api<Shipment>("shipments/", { method: "POST", body: JSON.stringify(payload) });
      setMessage(`Expédition enregistrée : ${s.lines.length} lot(s) pour ${s.customer_name}${s.container_number ? `, conteneur ${s.container_number}` : ""}.`);
      setLines({});
      setCoi("");
      setFormKey((k) => k + 1);
      load();
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <main>
      <Menu />
      <h1>Expéditions</h1>
      {message && <p style={{ background: "#e8f5e9", padding: 8, fontSize: "1.1em" }}>{message}</p>}
      {error && <p role="alert">{error}</p>}
      {options && (
        <form key={formKey} onSubmit={onSubmit} style={{ display: "grid", gap: 12, border: "1px solid #888", padding: 12 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            <label>
              Client{" "}
              <select name="customer" required defaultValue="">
                <option value="" disabled>
                  (choisir)
                </option>
                {options.customers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                    {c.city ? ` (${c.city})` : ""}
                  </option>
                ))}
              </select>
            </label>
            {options.sites.length > 1 && (
              <label>
                Site de départ{" "}
                <select name="site" required defaultValue="">
                  <option value="" disabled>
                    (choisir)
                  </option>
                  {options.sites.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          <strong>Lots chargés</strong>
          {options.lots.length === 0 ? (
            <p>Aucun lot expédiable (produit fini ou semi-fini disponible).</p>
          ) : (
            <table cellPadding={4} style={{ borderCollapse: "collapse", width: "100%" }}>
              <thead>
                <tr style={{ textAlign: "left" }}>
                  <th>Lot</th>
                  <th>Statut bio</th>
                  <th>En stock</th>
                  <th>Contrôle qualité</th>
                  <th>Quantité chargée</th>
                </tr>
              </thead>
              <tbody>
                {options.lots.map((l) => {
                  const line = lines[l.id] || { quantity: "", unit: l.conversions[0]?.unit_name || l.base_unit };
                  const set = (patch: Partial<Line>) => setLines((old) => ({ ...old, [l.id]: { ...line, ...patch } }));
                  return (
                    <tr key={l.id} style={{ borderTop: "1px solid #ddd" }}>
                      <td>
                        <strong>{l.code}</strong>
                        <br />
                        <small>
                          {l.article_name}
                          {l.site_name ? ` · ${l.site_name}` : ""}
                        </small>
                      </td>
                      <td>
                        <OrganicBadge status={l.organic_status} />
                      </td>
                      <td>{withUnit(l.balance, l.base_unit)}</td>
                      <td style={{ color: l.quality_result === "conforme" ? "#1b5e20" : "#8a5a00" }}>
                        {l.quality_result === "conforme" ? "Conforme" : "Aucun contrôle"}
                      </td>
                      <td>
                        <input aria-label={`Quantité ${l.code}`} value={line.quantity} onChange={(e) => set({ quantity: e.target.value })} inputMode="decimal" style={{ width: 80 }} />{" "}
                        <select aria-label="Unité" value={line.unit} onChange={(e) => set({ unit: e.target.value })}>
                          <option value={l.base_unit}>{withUnit(2, l.base_unit).replace(/^2 /, "")}</option>
                          {l.conversions.map((c) => (
                            <option key={c.unit_name} value={c.unit_name}>
                              {c.unit_name} ({withUnit(c.factor, l.base_unit)})
                            </option>
                          ))}
                        </select>{" "}
                        <button type="button" onClick={() => set({ quantity: l.balance, unit: l.base_unit })}>
                          Tout
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
          {unchecked.length > 0 && (
            <p style={{ color: "#8a5a00" }}>Attention : {unchecked.map((l) => l.code).join(", ")} sans contrôle qualité conforme.</p>
          )}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
            <label>
              N° de conteneur <input name="container_number" placeholder="ABCU1234567" maxLength={20} style={{ width: 130 }} />
            </label>
            <label>
              N° de plomb <input name="seal_number" maxLength={40} style={{ width: 130 }} />
            </label>
            <label>
              N° du certificat d&apos;inspection (COI TRACES){" "}
              <input value={coi} onChange={(e) => setCoi(e.target.value)} maxLength={60} style={{ width: 200 }} />
            </label>
            <label>
              N° de connaissement (BL) <input name="bill_of_lading" maxLength={60} style={{ width: 140 }} />
            </label>
          </div>
          {bio && !coi && (
            <p style={{ color: "#8a5a00" }}>
              Lot {ORGANIC.bio.toLowerCase()} ou en conversion vers l&apos;Union européenne : le certificat d&apos;inspection TRACES
              (COI) est exigé à l&apos;importation (règlement (UE) 2021/2306).
            </p>
          )}
          <LateEntry reasons={options.late_reasons} label="Date et heure du départ" />
          <div>
            <button type="submit" disabled={picked.length === 0} style={{ fontSize: "1.05em", padding: "8px 14px" }}>
              Enregistrer l&apos;expédition
            </button>
          </div>
        </form>
      )}
      <h2>Dernières expéditions</h2>
      {shipments.length === 0 ? (
        <p>Aucune expédition.</p>
      ) : (
        <table cellPadding={4} style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr style={{ textAlign: "left" }}>
              <th>Date</th>
              <th>Client</th>
              <th>Conteneur</th>
              <th>Documents</th>
              <th>Lots</th>
            </tr>
          </thead>
          <tbody>
            {shipments.map((s) => (
              <tr key={s.id} style={{ borderTop: "1px solid #ddd", verticalAlign: "top" }}>
                <td>{day(s.shipped_at)}</td>
                <td>
                  {s.customer_name}
                  {s.customer_city ? ` (${s.customer_city})` : ""}
                </td>
                <td>
                  {s.container_number}
                  {s.seal_number ? ` · plomb ${s.seal_number}` : ""}
                </td>
                <td>
                  {s.export_document_ref && <div>COI {s.export_document_ref}</div>}
                  {s.bill_of_lading && <div>BL {s.bill_of_lading}</div>}
                </td>
                <td>
                  {s.lines.map((l) => (
                    <div key={l.lot_code}>
                      {l.lot_code} : {withUnit(l.quantity, l.base_unit)} <OrganicBadge status={l.organic_status} />
                    </div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
