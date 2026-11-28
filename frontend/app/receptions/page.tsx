"use client";

// Reception d'une livraison fournisseur, pensee pour un operateur presse.
// Regle du projet : le moins de texte libre possible. Tout se choisit dans des listes, sauf le numero
// de lot ecrit par le fournisseur (une identite) et les mesures (quantite, date, temperature).
// Les regles (DLC obligatoire, temperature, motif) sont appliquees par l'API, l'ecran les rappelle.
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { LateEntry, LateFlag, ORGANIC, OrganicBadge, lateFields } from "@/components/Codes";
import { Person } from "@/components/Person";
import { api, ApiError } from "@/lib/api";

type Me = { id: string; username: string; role: string };
type Option = { code: string; label: string };
type Conversion = { unit_name: string; factor: string };
type Article = {
  id: string;
  code: string;
  name: string;
  article_type: string;
  base_unit: string;
  storage: string;
  shelf_life_days: number | null;
  conversions: Conversion[];
};
type Parcel = { id: string; code: string; locality: string; organic_status: string };
type Supplier = { id: string; name: string; city: string; parcels: Parcel[] };
type Site = { id: string; name: string };
type Options = {
  articles: Article[];
  suppliers: Supplier[];
  reception_reasons: Option[];
  reversal_reasons: Option[];
  late_reasons: Option[];
  organic_statuses: Option[];
  sites: Site[];
};
type Row = {
  movement_id: string;
  lot_id: string;
  lot_code: string;
  lot_status: string;
  article_code: string;
  article_name: string;
  base_unit: string;
  supplier_name: string | null;
  supplier_lot_code: string;
  quantity: string;
  block_reason: string;
  occurred_at: string;
  created_at: string;
  username: string | null;
  reversed: boolean;
  reversal_reason: string | null;
  can_reverse: boolean;
  organic_status: string;
  parcel_code: string | null;
  late: boolean;
};
type CreatedLot = { code: string; status: string; balance: string; base_unit: string; block_reason: string };

const TYPES: Record<string, string> = {
  matiere: "Matières premières",
  emballage: "Emballages",
  semi_fini: "Semi-finis",
  fini: "Produits finis",
};
const LOT_STATUS: Record<string, string> = { disponible: "Disponible", bloque: "Bloqué", detruit: "Détruit" };

function unitLabel(unit: string, quantity?: string | number | null): string {
  if (unit === "l") return "L";
  if (unit === "unite") return quantity !== undefined && quantity !== null && Math.abs(Number(quantity)) > 1 ? "unités" : "unité";
  return unit;
}
const fmt = (n: string | number) => Number(n).toLocaleString("fr-FR", { maximumFractionDigits: 3 });
const withUnit = (n: string | number, unit: string) => `${fmt(n)} ${unitLabel(unit, n)}`;
const when = (d: string) => new Date(d).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });

function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.body && typeof e.body === "object" && "detail" in e.body) return String((e.body as { detail: string }).detail);
    if (e.body && typeof e.body === "object")
      return Object.values(e.body as Record<string, unknown>)
        .map((v) => (Array.isArray(v) ? v.join(" ") : String(v)))
        .join(" ");
  }
  return "Erreur.";
}

// Motif choisi dans une liste fermee. La precision libre n'apparait (et n'est exigee) que pour « Autre ».
function ReasonPicker({ options }: { options: Option[] }) {
  const [code, setCode] = useState("");
  return (
    <>
      <label>
        Motif{" "}
        <select name="reason_code" required value={code} onChange={(e) => setCode(e.target.value)}>
          <option value="" disabled>
            (choisir)
          </option>
          {options.map((o) => (
            <option key={o.code} value={o.code}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      {code === "autre" && (
        <label>
          Précisez <input name="comment" required style={{ width: 220 }} />
        </label>
      )}
    </>
  );
}

function ReceptionForm({ options, onDone }: { options: Options; onDone: (lot: CreatedLot) => void }) {
  const [articleId, setArticleId] = useState("");
  const [unit, setUnit] = useState("");
  const [quantity, setQuantity] = useState("");
  const [visual, setVisual] = useState<"" | "ok" | "ko">("");
  const [supplierId, setSupplierId] = useState("");
  const [parcelId, setParcelId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const article = options.articles.find((a) => a.id === articleId);
  const needsDate = article !== undefined && article.article_type !== "emballage" && !article.shelf_life_days;
  const needsTemperature = article !== undefined && ["refrigere", "congele"].includes(article.storage);
  const supplier = options.suppliers.find((x) => x.id === supplierId);
  const parcels = supplier?.parcels || [];
  const parcel = parcels.find((p) => p.id === parcelId);
  const needsOrganic = article !== undefined && article.article_type !== "emballage";
  const factor = article && unit && unit !== article.base_unit ? Number(article.conversions.find((c) => c.unit_name === unit)?.factor || 0) : 1;
  const qty = Number(quantity.replace(",", "."));
  const grouped = useMemo(() => {
    const groups: Record<string, Article[]> = {};
    for (const a of options.articles) (groups[a.article_type] ||= []).push(a);
    return groups;
  }, [options.articles]);

  function chooseArticle(id: string) {
    setArticleId(id);
    setUnit(options.articles.find((a) => a.id === id)?.base_unit || "");
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!visual) return setError("Indiquez si le contrôle visuel est conforme ou non.");
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) || "").trim();
    const payload: Record<string, unknown> = {
      article: articleId,
      supplier: supplierId,
      supplier_lot_code: text("supplier_lot_code"),
      quantity: quantity.replace(",", ".").trim(),
      unit,
      visual_ok: visual === "ok",
    };
    if (text("expiry_date")) {
      payload.expiry_date = text("expiry_date");
      payload.date_type = text("date_type");
    }
    if (needsTemperature) payload.temperature_c = text("temperature_c").replace(",", ".");
    if (visual === "ko") {
      payload.reason_code = text("reason_code");
      payload.comment = text("comment");
    }
    if (text("site")) payload.site = text("site");
    if (needsOrganic) {
      if (parcelId) payload.parcel = parcelId;
      else payload.organic_status = text("organic_status");
    }
    Object.assign(payload, lateFields(form));
    setSending(true);
    try {
      const lot = await api<CreatedLot>("lots/receptions/", { method: "POST", body: JSON.stringify(payload) });
      onDone(lot); // le parent remonte un formulaire vide
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSending(false);
    }
  }

  const row = { display: "flex", flexWrap: "wrap" as const, gap: 8, alignItems: "center" };
  return (
    <form onSubmit={onSubmit} style={{ display: "grid", gap: 12, maxWidth: 760, border: "1px solid #888", padding: 12 }}>
      {options.sites.length > 1 && (
        <label>
          Site de réception{" "}
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
      <label>
        1. Fournisseur (producteur){" "}
        <select
          required
          value={supplierId}
          onChange={(e) => {
            setSupplierId(e.target.value);
            setParcelId("");
          }}
        >
          <option value="" disabled>
            (choisir)
          </option>
          {options.suppliers.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
              {s.city ? ` (${s.city})` : ""}
            </option>
          ))}
        </select>
      </label>
      <label>
        2. Article livré{" "}
        <select required value={articleId} onChange={(e) => chooseArticle(e.target.value)}>
          <option value="" disabled>
            (choisir)
          </option>
          {Object.keys(TYPES).filter((type) => grouped[type]).map((type) => [type, grouped[type]] as const).map(([type, list]) => (
            <optgroup key={type} label={TYPES[type]}>
              {list.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.code} {a.name}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </label>
      {article && (
        <>
          <div style={row}>
            <label>
              3. Quantité <input value={quantity} onChange={(e) => setQuantity(e.target.value)} required inputMode="decimal" style={{ width: 90 }} />
            </label>
            <select aria-label="Unité" value={unit} onChange={(e) => setUnit(e.target.value)}>
              <option value={article.base_unit}>{unitLabel(article.base_unit, 2)}</option>
              {article.conversions.map((c) => (
                <option key={c.unit_name} value={c.unit_name}>
                  {c.unit_name} ({withUnit(c.factor, article.base_unit)})
                </option>
              ))}
            </select>
            {qty > 0 && factor > 0 && (
              <span style={{ color: "#555" }}>
                soit <strong>{withUnit(qty * factor, article.base_unit)}</strong> en stock
              </span>
            )}
          </div>
          {needsOrganic && (
            <div style={row}>
              {parcels.length > 0 && (
                <label>
                  Parcelle{" "}
                  <select value={parcelId} onChange={(e) => setParcelId(e.target.value)}>
                    <option value="">(pas de parcelle : choisir le statut bio)</option>
                    {parcels.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.code}
                        {p.locality ? ` · ${p.locality}` : ""} · {ORGANIC[p.organic_status]}
                      </option>
                    ))}
                  </select>
                </label>
              )}
              {parcel ? (
                <span>
                  Statut bio repris de la parcelle : <OrganicBadge status={parcel.organic_status} />
                </span>
              ) : (
                <span>
                  Statut bio :{" "}
                  {options.organic_statuses.map((o) => (
                    <label key={o.code} style={{ marginRight: 8 }}>
                      <input type="radio" name="organic_status" value={o.code} required /> {o.label}
                    </label>
                  ))}
                </span>
              )}
            </div>
          )}
          <label>
            4. Numéro de lot du fournisseur <input name="supplier_lot_code" style={{ width: 200 }} />{" "}
            <small style={{ color: "#555" }}>(tel qu&apos;écrit sur l&apos;étiquette, si le fournisseur en donne un)</small>
          </label>
          <div style={row}>
            <span>
              5. Date limite
              {needsDate
                ? ""
                : article?.shelf_life_days
                  ? ` (facultative : vide, DDM à ${article.shelf_life_days} jours)`
                  : " (facultative pour un emballage)"}{" "}
              :
            </span>
            <label>
              <input type="radio" name="date_type" value="dlc" required={needsDate} /> DLC (à consommer jusqu&apos;au)
            </label>
            <label>
              <input type="radio" name="date_type" value="ddm" /> DDM (de préférence avant)
            </label>
            <input type="date" name="expiry_date" aria-label="Date limite" required={needsDate} />
          </div>
          {needsTemperature && (
            <label>
              6. Température à réception <input name="temperature_c" required inputMode="decimal" style={{ width: 70 }} /> °C{" "}
              <small style={{ color: "#555" }}>(article {article.storage === "congele" ? "congelé" : "réfrigéré"})</small>
            </label>
          )}
          <fieldset style={{ border: "none", padding: 0, margin: 0 }}>
            <legend>{needsTemperature ? "7" : "6"}. Contrôle visuel de la livraison</legend>
            <label style={{ marginRight: 16 }}>
              <input type="radio" name="visual" checked={visual === "ok"} onChange={() => setVisual("ok")} /> Conforme
            </label>
            <label>
              <input type="radio" name="visual" checked={visual === "ko"} onChange={() => setVisual("ko")} /> Non conforme
            </label>
          </fieldset>
          {visual === "ko" && (
            <div style={row}>
              <ReasonPicker options={options.reception_reasons} />
              <span style={{ color: "#a00" }}>Le lot sera créé bloqué.</span>
            </div>
          )}
          <LateEntry reasons={options.late_reasons} />
          <div>
            <button type="submit" disabled={sending}>
              {sending ? "Enregistrement..." : "Enregistrer la réception"}
            </button>
          </div>
        </>
      )}
      {error && <p role="alert">{error}</p>}
    </form>
  );
}

function ReceptionRow({ row, reasons, onChanged }: { row: Row; reasons: Option[]; onChanged: (message: string) => void }) {
  const [reversing, setReversing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onReverse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    try {
      await api(`movements/${row.movement_id}/reverse/`, {
        method: "POST",
        body: JSON.stringify({ reason_code: form.get("reason_code"), comment: form.get("comment") || "" }),
      });
      onChanged(`Réception du lot ${row.lot_code} annulée. Le stock du lot revient à zéro.`);
    } catch (e) {
      setError(errorText(e));
    }
  }

  let state = LOT_STATUS[row.lot_status] || row.lot_status;
  if (row.reversed) state = `Annulée : ${row.reversal_reason}`;
  else if (row.lot_status === "bloque" && row.block_reason) state = `Bloqué : ${row.block_reason}`;
  return (
    <tr style={{ borderTop: "1px solid #ddd", verticalAlign: "top" }}>
      <td>
        {when(row.occurred_at)}
        <br />
        <LateFlag late={row.late} />
      </td>
      <td>
        <strong>{row.lot_code}</strong> <OrganicBadge status={row.organic_status} />
        <br />
        <small>
          {row.article_code} {row.article_name}
        </small>
      </td>
      <td>
        {row.supplier_name}
        {row.parcel_code && (
          <>
            <br />
            <small>parcelle {row.parcel_code}</small>
          </>
        )}
        {row.supplier_lot_code && (
          <>
            <br />
            <small>lot {row.supplier_lot_code}</small>
          </>
        )}
      </td>
      <td>{withUnit(row.quantity, row.base_unit)}</td>
      <td>
        <Person username={row.username} />
      </td>
      <td>{state}</td>
      <td>
        {row.can_reverse && !reversing && <button onClick={() => setReversing(true)}>Annuler</button>}
        {row.can_reverse && reversing && (
          <form onSubmit={onReverse} style={{ display: "grid", gap: 4 }}>
            <ReasonPicker options={reasons} />
            <span>
              <button type="submit">Confirmer l&apos;annulation</button> <button type="button" onClick={() => setReversing(false)}>Retour</button>
            </span>
          </form>
        )}
        {!row.can_reverse && !row.reversed && <small>Lot déjà utilisé : plus d&apos;annulation</small>}
        {error && <p role="alert">{error}</p>}
      </td>
    </tr>
  );
}

export default function Receptions() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [options, setOptions] = useState<Options | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formKey, setFormKey] = useState(0);

  const loadRows = useCallback(() => {
    api<Row[]>("lots/receptions/").then(setRows).catch((e) => setError(errorText(e)));
  }, []);

  useEffect(() => {
    api<Me>("auth/me/").then(setMe).catch(() => setMe(null));
  }, []);
  useEffect(() => {
    if (!me || me.role === "lecture") return;
    api<Options>("lots/receptions/options/").then(setOptions).catch((e) => setError(errorText(e)));
    loadRows();
  }, [me, loadRows]);

  if (me === undefined) return <main><p>Chargement...</p></main>;
  if (me === null || me.role === "lecture")
    return (
      <main>
        <p role="alert">{me === null ? "Connectez-vous d'abord." : "Le rôle Lecture ne peut pas enregistrer de réception."}</p>
        <a href="/">Accueil</a>
      </main>
    );

  function created(lot: CreatedLot) {
    const blocked = lot.status === "bloque";
    setMessage(
      `Lot ${lot.code} créé : ${withUnit(lot.balance, lot.base_unit)}, ${blocked ? `bloqué (${lot.block_reason})` : "disponible"}. ` +
        "Écrivez ce numéro sur la livraison.",
    );
    setFormKey((k) => k + 1);
    loadRows();
  }

  return (
    <main>
      <h1>Réceptions</h1>
      <p>
        Enregistrez chaque livraison à son arrivée. Tracalys crée le lot, calcule la quantité dans l&apos;unité de l&apos;article et
        démarre la traçabilité. Vous êtes <strong>{me.username}</strong>.
      </p>
      {message && <p style={{ background: "#e8f5e9", padding: 8, fontSize: "1.1em" }}>{message}</p>}
      {error && <p role="alert">{error}</p>}
      <h2>Enregistrer une livraison</h2>
      {options === null ? (
        <p>Chargement des listes...</p>
      ) : options.articles.length === 0 || options.suppliers.length === 0 ? (
        <p>
          Il manque {options.articles.length === 0 ? "des articles" : "des fournisseurs"} : demandez à l&apos;administrateur ou à la
          Qualité de les créer dans les référentiels.
        </p>
      ) : (
        <ReceptionForm key={formKey} options={options} onDone={created} />
      )}
      <h2>{me.role === "operateur" ? "Mes dernières réceptions" : "Dernières réceptions"}</h2>
      <p style={{ color: "#555" }}>
        Une erreur ? Annulez la réception tant que le lot n&apos;a pas servi, puis enregistrez-la à nouveau. Rien n&apos;est effacé :
        l&apos;annulation est tracée au journal.
      </p>
      {rows.length === 0 ? (
        <p>Aucune réception.</p>
      ) : (
        <table style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr style={{ textAlign: "left" }}>
              <th>Date</th>
              <th>Lot</th>
              <th>Fournisseur</th>
              <th>Quantité</th>
              <th>Par</th>
              <th>État</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <ReceptionRow
                key={r.movement_id}
                row={r}
                reasons={options?.reversal_reasons || []}
                onChanged={(text) => {
                  setMessage(text);
                  loadRows();
                }}
              />
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
