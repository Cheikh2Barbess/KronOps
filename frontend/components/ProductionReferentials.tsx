"use client";

// Referentiels du suivi bio et de la production : parcelles des producteurs, sites (usines), equipements.
// Ecriture : Admin et Qualite (verifie par l'API). Le statut bio et les types se choisissent dans des listes.
import { FormEvent, useCallback, useEffect, useState } from "react";
import { ORGANIC, OrganicBadge, errorText } from "@/components/Codes";
import { api } from "@/lib/api";

type Parcel = {
  id: string;
  producer: string;
  producer_name: string;
  code: string;
  locality: string;
  area_ha: string | null;
  organic_status: string;
  is_active: boolean;
};
type Supplier = { id: string; name: string };
type Site = { id: string; name: string; address: string };
type Equipment = { id: string; code: string; name: string; equipment_type: string; site: string | null; site_name: string | null; is_active: boolean };

const EQUIPMENT_TYPES: Record<string, string> = {
  sechoir: "Séchoir ou four",
  murissement: "Chambre ou aire de mûrissement",
  tri: "Table ou ligne de tri",
  preparation: "Ligne de préparation",
  conditionnement: "Ligne de conditionnement",
  autre: "Autre",
};
const box = { display: "grid", gap: 8, padding: 12, border: "1px solid #888", margin: "8px 0", maxWidth: 640 };

function ParcelEditor({ parcel, suppliers, onDone }: { parcel: Parcel | null; suppliers: Supplier[]; onDone: () => void }) {
  const [error, setError] = useState<string | null>(null);
  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const area = String(form.get("area_ha") || "").trim().replace(",", ".");
    const payload: Record<string, unknown> = {
      producer: form.get("producer"),
      code: String(form.get("code") || "").trim(),
      locality: String(form.get("locality") || "").trim(),
      area_ha: area || null,
      organic_status: form.get("organic_status"),
      is_active: form.get("is_active") === "on",
    };
    try {
      if (parcel) await api(`parcels/${parcel.id}/`, { method: "PATCH", body: JSON.stringify(payload) });
      else await api("parcels/", { method: "POST", body: JSON.stringify(payload) });
      onDone();
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <form onSubmit={onSubmit} style={box}>
      <strong>{parcel ? `Modifier la parcelle ${parcel.code}` : "Nouvelle parcelle"}</strong>
      <label>
        Producteur ou groupement{" "}
        <select name="producer" required defaultValue={parcel?.producer ?? ""}>
          <option value="" disabled>
            (choisir)
          </option>
          {suppliers.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Code parcelle <input name="code" required maxLength={50} defaultValue={parcel?.code ?? ""} />
      </label>
      <label>
        Localité <input name="locality" maxLength={100} defaultValue={parcel?.locality ?? ""} />
      </label>
      <label>
        Surface (ha) <input name="area_ha" inputMode="decimal" style={{ width: 80 }} defaultValue={parcel?.area_ha ?? ""} />
      </label>
      <div>
        Statut bio :{" "}
        {Object.entries(ORGANIC).map(([code, label]) => (
          <label key={code} style={{ marginRight: 12 }}>
            <input type="radio" name="organic_status" value={code} required defaultChecked={parcel?.organic_status === code} /> {label}
          </label>
        ))}
      </div>
      <small style={{ color: "#555" }}>
        Le statut est recopié sur chaque lot reçu de cette parcelle. Le changer plus tard ne modifie pas les lots déjà reçus.
      </small>
      <label>
        <input type="checkbox" name="is_active" defaultChecked={parcel?.is_active ?? true} /> Active
      </label>
      {error && <p role="alert">{error}</p>}
      <div>
        <button type="submit">Enregistrer</button> <button type="button" onClick={onDone}>Annuler</button>
      </div>
    </form>
  );
}

export function ParcelSection() {
  const [rows, setRows] = useState<Parcel[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const load = useCallback(() => {
    const q = status ? `&organic_status=${status}` : "";
    api<{ results: Parcel[] }>(`parcels/?page_size=200${q}`).then((d) => setRows(d.results)).catch(() => setRows([]));
  }, [status]);
  useEffect(load, [load]);
  useEffect(() => {
    api<{ results: Supplier[] }>("partners/?role=supplier&page_size=200")
      .then((d) => setSuppliers(d.results))
      .catch(() => setSuppliers([]));
  }, []);
  const done = () => {
    setEditing(null);
    load();
  };
  return (
    <section>
      <h2>Parcelles des producteurs</h2>
      <p>
        <button onClick={() => setEditing("new")}>Ajouter une parcelle</button>{" "}
        <label>
          Statut bio{" "}
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">(tous)</option>
            {Object.entries(ORGANIC).map(([c, l]) => (
              <option key={c} value={c}>
                {l}
              </option>
            ))}
          </select>
        </label>
      </p>
      {editing === "new" && <ParcelEditor parcel={null} suppliers={suppliers} onDone={done} />}
      {rows.length === 0 ? (
        <p>Aucune parcelle.</p>
      ) : (
        <table cellPadding={4} style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr style={{ textAlign: "left" }}>
              <th>Parcelle</th>
              <th>Producteur</th>
              <th>Localité</th>
              <th>Surface</th>
              <th>Statut bio</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p) =>
              editing === p.id ? (
                <tr key={p.id}>
                  <td colSpan={6}>
                    <ParcelEditor parcel={p} suppliers={suppliers} onDone={done} />
                  </td>
                </tr>
              ) : (
                <tr key={p.id} style={{ borderTop: "1px solid #ddd", opacity: p.is_active ? 1 : 0.5 }}>
                  <td>{p.code}</td>
                  <td>{p.producer_name}</td>
                  <td>{p.locality}</td>
                  <td>{p.area_ha ? `${Number(p.area_ha).toLocaleString("fr-FR")} ha` : ""}</td>
                  <td>
                    <OrganicBadge status={p.organic_status} />
                  </td>
                  <td>
                    <button onClick={() => setEditing(p.id)}>Modifier</button>
                  </td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      )}
    </section>
  );
}

export function SiteSection() {
  const [rows, setRows] = useState<Site[]>([]);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    api<Site[]>("sites/").then(setRows).catch(() => setRows([]));
  }, []);
  useEffect(load, [load]);
  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formEl = event.currentTarget;
    const form = new FormData(formEl);
    setError(null);
    try {
      await api("sites/", {
        method: "POST",
        body: JSON.stringify({ name: String(form.get("name") || "").trim(), address: String(form.get("address") || "").trim() }),
      });
      formEl.reset();
      load();
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <section>
      <h2>Sites (usines)</h2>
      <p style={{ color: "#555" }}>
        Avec plusieurs sites, chaque réception, étape et expédition indique son site. Avec un seul, il est choisi
        automatiquement.
      </p>
      <ul>
        {rows.map((s) => (
          <li key={s.id}>
            {s.name}
            {s.address ? ` · ${s.address}` : ""}
          </li>
        ))}
        {rows.length === 0 && <li>Aucun site déclaré.</li>}
      </ul>
      <form onSubmit={onSubmit} style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input name="name" required placeholder="Nom du site" maxLength={200} />
        <input name="address" placeholder="Adresse (facultatif)" style={{ width: 260 }} />
        <button type="submit">Ajouter le site</button>
      </form>
      {error && <p role="alert">{error}</p>}
    </section>
  );
}

function EquipmentEditor({ item, sites, onDone }: { item: Equipment | null; sites: Site[]; onDone: () => void }) {
  const [error, setError] = useState<string | null>(null);
  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = {
      code: String(form.get("code") || "").trim(),
      name: String(form.get("name") || "").trim(),
      equipment_type: form.get("equipment_type"),
      site: form.get("site") || null,
      is_active: form.get("is_active") === "on",
    };
    try {
      if (item) await api(`equipment/${item.id}/`, { method: "PATCH", body: JSON.stringify(payload) });
      else await api("equipment/", { method: "POST", body: JSON.stringify(payload) });
      onDone();
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <form onSubmit={onSubmit} style={box}>
      <strong>{item ? `Modifier ${item.code}` : "Nouvel équipement"}</strong>
      <label>
        Code <input name="code" required maxLength={30} defaultValue={item?.code ?? ""} />
      </label>
      <label>
        Nom <input name="name" required maxLength={100} defaultValue={item?.name ?? ""} />
      </label>
      <label>
        Type{" "}
        <select name="equipment_type" required defaultValue={item?.equipment_type ?? ""}>
          <option value="" disabled>
            (choisir)
          </option>
          {Object.entries(EQUIPMENT_TYPES).map(([c, l]) => (
            <option key={c} value={c}>
              {l}
            </option>
          ))}
        </select>
      </label>
      {sites.length > 0 && (
        <label>
          Site{" "}
          <select name="site" defaultValue={item?.site ?? ""} required={sites.length > 1}>
            <option value="">(choisir)</option>
            {sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        <input type="checkbox" name="is_active" defaultChecked={item?.is_active ?? true} /> Actif
      </label>
      {error && <p role="alert">{error}</p>}
      <div>
        <button type="submit">Enregistrer</button> <button type="button" onClick={onDone}>Annuler</button>
      </div>
    </form>
  );
}

export function EquipmentSection() {
  const [rows, setRows] = useState<Equipment[]>([]);
  const [sites, setSites] = useState<Site[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const load = useCallback(() => {
    api<Equipment[]>("equipment/").then(setRows).catch(() => setRows([]));
    api<Site[]>("sites/").then(setSites).catch(() => setSites([]));
  }, []);
  useEffect(load, [load]);
  const done = () => {
    setEditing(null);
    load();
  };
  return (
    <section>
      <h2>Équipements (séchoirs, mûrissement, lignes)</h2>
      <p>
        <button onClick={() => setEditing("new")}>Ajouter un équipement</button>
      </p>
      {editing === "new" && <EquipmentEditor item={null} sites={sites} onDone={done} />}
      <table cellPadding={4} style={{ borderCollapse: "collapse", width: "100%" }}>
        <tbody>
          {rows.map((e) =>
            editing === e.id ? (
              <tr key={e.id}>
                <td colSpan={5}>
                  <EquipmentEditor item={e} sites={sites} onDone={done} />
                </td>
              </tr>
            ) : (
              <tr key={e.id} style={{ borderTop: "1px solid #ddd", opacity: e.is_active ? 1 : 0.5 }}>
                <td>{e.code}</td>
                <td>{e.name}</td>
                <td>{EQUIPMENT_TYPES[e.equipment_type] || e.equipment_type}</td>
                <td>{e.site_name || ""}</td>
                <td>
                  <button onClick={() => setEditing(e.id)}>Modifier</button>
                </td>
              </tr>
            ),
          )}
          {rows.length === 0 && (
            <tr>
              <td>Aucun équipement.</td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}
