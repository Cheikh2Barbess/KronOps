"use client";

// Transfert d'un lot d'une usine a une autre. Tout le lot : il garde son code. Une partie : un nouveau lot nait a
// l'usine d'arrivee (le numero a ecrire sur l'etiquette s'affiche), relie au lot d'origine pour le rappel.
import { FormEvent, useCallback, useEffect, useState } from "react";
import { LateEntry, LateFlag, Option, OrganicBadge, errorText, lateFields, when, withUnit } from "@/components/Codes";
import { api } from "@/lib/api";

type Me = { username: string; role: string };
type Lot = {
  id: string;
  code: string;
  article_name: string;
  base_unit: string;
  organic_status: string;
  status: string;
  site: string | null;
  site_name: string | null;
  balance: string;
};
type Transfer = {
  id: string;
  source_lot_code: string;
  lot_code: string;
  whole_lot: boolean;
  article_name: string;
  base_unit: string;
  organic_status: string;
  from_site_name: string | null;
  to_site_name: string;
  quantity: string;
  occurred_at: string;
  late: boolean;
  username: string | null;
};
type Options = { sites: { id: string; name: string }[]; lots: Lot[]; late_reasons: Option[] };
const big = { fontSize: "1.1em", padding: "10px 14px", minHeight: 44 };

export default function Transferts() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [options, setOptions] = useState<Options | null>(null);
  const [rows, setRows] = useState<Transfer[]>([]);
  const [lotId, setLotId] = useState("");
  const [whole, setWhole] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formKey, setFormKey] = useState(0);

  const load = useCallback(() => {
    api<Options>("lots/transfers/options/").then(setOptions).catch((e) => setError(errorText(e)));
    api<Transfer[]>("lots/transfers/").then(setRows).catch(() => setRows([]));
  }, []);
  useEffect(() => {
    api<Me>("auth/me/").then(setMe).catch(() => setMe(null));
  }, []);
  useEffect(() => {
    if (me) load();
  }, [me, load]);

  if (me === undefined) return <main><p>Chargement...</p></main>;
  if (me === null)
    return (
      <main>
        <p role="alert">Connectez-vous d&apos;abord.</p>
        <a href="/">Accueil</a>
      </main>
    );
  const canTransfer = ["admin", "production", "operateur"].includes(me.role);
  const lot = options?.lots.find((l) => l.id === lotId);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    const payload: Record<string, unknown> = { lot: lotId, to_site: form.get("to_site"), ...lateFields(form) };
    if (!whole) payload.quantity = String(form.get("quantity") || "").replace(",", ".");
    try {
      const t = await api<Transfer>("lots/transfers/", { method: "POST", body: JSON.stringify(payload) });
      setMessage(
        t.whole_lot
          ? `Lot ${t.lot_code} transféré en entier vers ${t.to_site_name}. Il garde son numéro.`
          : `${withUnit(t.quantity, t.base_unit)} transférés vers ${t.to_site_name} : nouveau lot ${t.lot_code}. Écrivez ce numéro sur l'étiquette.`,
      );
      setLotId("");
      setWhole(true);
      setFormKey((k) => k + 1);
      load();
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <main>
      <h1>Transferts entre usines</h1>
      <p>
        Un lot se consomme et s&apos;expédie depuis l&apos;usine où il se trouve. Pour l&apos;utiliser ailleurs, transférez-le. Le statut
        bio, la parcelle, la date limite et un éventuel blocage suivent le lot.
      </p>
      {message && <p className="notice" role="status">{message}</p>}
      {error && (
        <p role="alert" style={{ color: "#b00020" }}>
          {error}
        </p>
      )}
      {canTransfer && options && options.sites.length < 2 && (
        <p>Il faut au moins deux sites pour transférer un lot. Ajoutez-les dans les référentiels.</p>
      )}
      {canTransfer && options && options.sites.length >= 2 && (
        <form key={formKey} onSubmit={onSubmit} style={{ display: "grid", gap: 12, maxWidth: 860, border: "1px solid var(--line)", borderRadius: "var(--radius)", background: "var(--surface)", padding: 12 }}>
          <label>
            <strong>1. Lot</strong>{" "}
            <select value={lotId} onChange={(e) => setLotId(e.target.value)} required style={{ ...big, maxWidth: 600 }}>
              <option value="">(choisir)</option>
              {options.lots.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.site_name || "sans site"} · {l.code} · {l.article_name} · {withUnit(l.balance, l.base_unit)}
                  {l.status === "bloque" ? " · bloqué" : ""}
                </option>
              ))}
            </select>{" "}
            {lot && <OrganicBadge status={lot.organic_status} />}
          </label>
          {lot && (
            <>
              <label>
                <strong>2. Vers</strong>{" "}
                <select name="to_site" required defaultValue="" style={big}>
                  <option value="" disabled>
                    (choisir l&apos;usine d&apos;arrivée)
                  </option>
                  {options.sites
                    .filter((s) => s.id !== lot.site)
                    .map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                </select>
              </label>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center" }}>
                <strong>3. Quantité</strong>
                <label>
                  <input type="radio" checked={whole} onChange={() => setWhole(true)} /> Tout le lot ({withUnit(lot.balance, lot.base_unit)})
                </label>
                <label>
                  <input type="radio" checked={!whole} onChange={() => setWhole(false)} /> Une partie
                </label>
                {!whole && (
                  <label>
                    <input name="quantity" required inputMode="decimal" style={{ ...big, width: 110 }} />{" "}
                    {withUnit(2, lot.base_unit).replace(/^2 /, "")}
                  </label>
                )}
              </div>
              <LateEntry reasons={options.late_reasons} label="Départ réel" />
              <div>
                <button type="submit" style={{ ...big, fontWeight: "bold" }}>
                  Enregistrer le transfert
                </button>
              </div>
            </>
          )}
        </form>
      )}
      <h2>Derniers transferts</h2>
      {rows.length === 0 ? (
        <p>Aucun transfert.</p>
      ) : (
        <table cellPadding={4} style={{ width: "100%" }}>
          <thead>
            <tr style={{ textAlign: "left" }}>
              <th>Date</th>
              <th>Lot</th>
              <th className="num">Quantité</th>
              <th>De</th>
              <th>Vers</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <tr key={t.id} style={{ verticalAlign: "top" }}>
                <td>
                  {when(t.occurred_at)}
                  <br />
                  <LateFlag late={t.late} />
                </td>
                <td>
                  <strong>{t.lot_code}</strong> <OrganicBadge status={t.organic_status} />
                  <br />
                  <small>{t.whole_lot ? "lot entier" : `partie du lot ${t.source_lot_code}`} · {t.article_name}</small>
                </td>
                <td className="num">{withUnit(t.quantity, t.base_unit)}</td>
                <td>{t.from_site_name || "sans site"}</td>
                <td>{t.to_site_name}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
