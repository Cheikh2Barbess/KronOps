"use client";

// Journal d'audit (US-03) : qui a cree, modifie ou annule quoi, quand, avec ancienne et nouvelle valeur.
// Lecture seule. Reserve aux roles Admin et Qualite (controle fait par l'API).
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

type Values = Record<string, unknown> | null;
type Entry = {
  id: string;
  created_at: string;
  action: string;
  entity_type: string;
  entity_label: string;
  entity_id: string;
  username: string | null;
  old_values: Values;
  new_values: Values;
  changed_fields: string[];
  subject: string;
  unit: string | null;
  refs: Record<string, string>;
};
type Page = { count: number; next: string | null; previous: string | null; results: Entry[] };
type AuditUser = { id: string; username: string };
type Option = { code: string; label: string };

const ACTIONS: Record<string, string> = {
  create: "Création",
  update: "Modification",
  import: "Import",
  cancel: "Annulation",
  block: "Blocage",
  request: "Demande",
  approve: "Validation",
  reject: "Refus",
  release: "Déblocage",
  destroy: "Destruction",
};
const ENTITY_TYPES: Record<string, string> = {
  "catalog.article": "Articles",
  "catalog.partner": "Fournisseurs et clients",
  "catalog.unitconversion": "Conversions d'unités",
  "tenants.site": "Sites",
  "lots.lot": "Lots",
  "lots.movement": "Mouvements",
  "lots.approvalrequest": "Demandes de double validation",
  "lots.lotlink": "Liens entre lots",
};
// Nom de l'objet au singulier, en tete de la colonne « Objet ».
const ENTITY_ONE: Record<string, string> = {
  "catalog.article": "Article",
  "catalog.partner": "Partenaire",
  "catalog.unitconversion": "Conditionnement",
  "tenants.site": "Site",
  "lots.lot": "Lot",
  "lots.movement": "Mouvement",
  "lots.approvalrequest": "Demande",
  "lots.lotlink": "Lien entre lots",
};

// Libelles francais des champs enregistres dans le journal.
const FIELDS: Record<string, string> = {
  code: "code",
  name: "nom",
  article_type: "type",
  base_unit: "unité",
  shelf_life_days: "durée de vie",
  storage: "conservation",
  is_active: "actif",
  allergens: "allergènes",
  is_supplier: "fournisseur",
  is_customer: "client",
  address: "adresse",
  city: "ville",
  contact_name: "contact",
  phone: "téléphone",
  email: "e-mail",
  unit_name: "conditionnement",
  factor: "contenance",
  status: "statut",
  block_reason: "motif de blocage",
  block_code: "motif de blocage",
  action: "action",
  quantity: "quantité",
  reason: "motif",
  reason_code: "motif",
  comment: "précision",
  type: "type",
  lot_id: "lot",
  article_id: "article",
  supplier_id: "fournisseur",
  partner_id: "partenaire",
  reversal_id: "contre-mouvement",
  parent_lot_id: "lot utilisé",
  child_lot_id: "lot produit",
  decided_by: "décidé par",
  decision_code: "motif du refus",
  decision_comment: "précision du refus",
  date_type: "type de date",
  expiry_date: "date limite",
  production_date: "date de fabrication",
  supplier_lot_code: "lot fournisseur",
  reception_visual_ok: "contrôle visuel conforme",
  reception_temperature_c: "température à réception",
};
// Valeurs codees traduites, par champ.
const VALUES: Record<string, Record<string, string>> = {
  status: {
    disponible: "disponible", bloque: "bloqué", detruit: "détruit",
    pending: "en attente", approved: "validée", rejected: "refusée", cancelled: "annulée",
  },
  action: { release: "déblocage", destroy: "destruction", scrap: "rebut", adjust: "ajustement" },
  type: {
    reception: "réception", production: "production", retour: "retour", consommation: "consommation",
    expedition: "expédition", rebut: "rebut", ajustement: "ajustement", destruction: "destruction", annulation: "annulation",
  },
  date_type: { dlc: "DLC", ddm: "DDM" },
  base_unit: { kg: "kg", l: "L", unite: "unité" },
  article_type: { matiere: "matière première", emballage: "emballage", semi_fini: "semi-fini", fini: "produit fini" },
  storage: { ambiant: "ambiant", refrigere: "réfrigéré", congele: "congelé" },
};
const PRESENCE: Record<string, string> = { contient: "contient", peut_contenir: "peut contenir", absent: "absent" };
// Un code n'est pas affiche quand son texte lisible est deja dans la meme ligne.
const SHADOWED: Record<string, string> = { block_code: "block_reason", reason_code: "reason" };
// Champs portes par la colonne « Objet » : inutile de les repeter dans le detail.
const IN_SUBJECT = new Set(["code", "name", "unit_name", "article_id", "lot_id"]);

const label = (field: string) => FIELDS[field] || field.replace(/_/g, " ");
const num = (n: unknown) => Number(n).toLocaleString("fr-FR", { maximumFractionDigits: 3 });
const unitName = (unit: string | null, n?: unknown) =>
  unit === "l" ? "L" : unit === "unite" ? (Math.abs(Number(n)) > 1 ? "unités" : "unité") : unit || "";
const day = (iso: string) => {
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}/${m}/${y}`;
};
const stamp = (iso: string) => new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });

type Ctx = { entry: Entry; codes: Record<string, string>; allergens: Record<string, string> };

function show(field: string, value: unknown, ctx: Ctx): string {
  if (value === null || value === undefined || value === "") return "(vide)";
  if (typeof value === "boolean") return value ? "oui" : "non";
  if (field === "allergens" && typeof value === "object") {
    // On ne liste que les allergenes presents ou possibles.
    const present = Object.entries(value as Record<string, unknown>).filter(([, v]) => v !== "absent");
    return present.length
      ? present.map(([k, v]) => `${ctx.allergens[k] || k} : ${PRESENCE[String(v)] || String(v)}`).join(", ")
      : "aucun";
  }
  const text = String(value);
  if (field.endsWith("_id")) return ctx.entry.refs[text] || "(objet introuvable)";
  if (VALUES[field]) return VALUES[field][text] || text;
  if (["reason_code", "decision_code", "block_code"].includes(field)) return ctx.codes[text] || text;
  if (field === "quantity") return `${num(text)} ${unitName(ctx.entry.unit, text)}`.trim();
  if (field === "factor") return `${num(text)} ${unitName(ctx.entry.unit, text)}`.trim();
  if (field === "shelf_life_days") return `${text} jours`;
  if (field === "reception_temperature_c") return `${num(text)} °C`;
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return day(text);
  return text;
}

function visible(field: string, values: Record<string, unknown>[], ctx: Ctx, creation: boolean): boolean {
  const twin = SHADOWED[field];
  if (twin && values.some((v) => v[twin])) return false;
  if (creation && IN_SUBJECT.has(field) && ctx.entry.subject) return false;
  return true;
}

function Changes({ ctx }: { ctx: Ctx }) {
  const { entry } = ctx;
  const oldV = entry.old_values || {};
  const newV = entry.new_values || {};
  if (entry.changed_fields.length === 0) {
    // Creation ou import : on montre les valeurs saisies.
    const items = Object.entries(newV).filter(([k, v]) => v !== null && v !== "" && visible(k, [newV], ctx, true));
    return (
      <span>
        {items.map(([k, v], i) => (
          <span key={k}>
            {i > 0 && " · "}
            {label(k)} : <strong>{show(k, v, ctx)}</strong>
          </span>
        ))}
      </span>
    );
  }
  const fields = entry.changed_fields.filter((f) => visible(f, [oldV, newV], ctx, false));
  const extra = Object.entries(newV).filter(([k, v]) => !(k in oldV) && v !== null && v !== "" && visible(k, [oldV, newV], ctx, false));
  return (
    <ul style={{ margin: 0, paddingLeft: 16 }}>
      {fields.filter((f) => f in oldV).map((field) => {
        const before = oldV[field];
        const after = newV[field];
        if (field === "allergens" && before && after && typeof before === "object" && typeof after === "object") {
          // On ne montre que les allergenes qui changent.
          const b = before as Record<string, unknown>;
          const a = after as Record<string, unknown>;
          const keys = Object.keys({ ...b, ...a }).filter((k) => b[k] !== a[k]);
          return (
            <li key={field}>
              allergènes :{" "}
              {keys.map((k) => `${ctx.allergens[k] || k} ${PRESENCE[String(b[k])] || "(vide)"} → ${PRESENCE[String(a[k])] || "(vide)"}`).join(", ")}
            </li>
          );
        }
        if (!(field in newV))
          // Ex. annulation : l'ancienne valeur decrit le mouvement annule, il n'y a pas de « nouvelle » valeur.
          return (
            <li key={field}>
              {label(field)} : {show(field, before, ctx)}
            </li>
          );
        return (
          <li key={field}>
            {label(field)} : {show(field, before, ctx)} → <strong>{show(field, after, ctx)}</strong>
          </li>
        );
      })}
      {extra.map(([k, v]) => (
        <li key={k}>
          {label(k)} : <strong>{show(k, v, ctx)}</strong>
        </li>
      ))}
    </ul>
  );
}

export default function Journal() {
  const [page, setPage] = useState<Page | null>(null);
  const [users, setUsers] = useState<AuditUser[]>([]);
  const [codes, setCodes] = useState<Record<string, string>>({});
  const [allergens, setAllergens] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("");
  const [pageNumber, setPageNumber] = useState(1);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    const params = new URLSearchParams(query);
    params.set("page", String(pageNumber));
    api<Page>(`audit/?${params.toString()}`)
      .then(setPage)
      .catch((e) =>
        setError(
          e instanceof ApiError && e.status === 403
            ? "Réservé aux rôles Admin et Qualité (ou vous n'êtes pas connecté)."
            : "Erreur de chargement."
        )
      );
  }, [query, pageNumber]);

  useEffect(load, [load]);
  useEffect(() => {
    api<AuditUser[]>("audit/users/").then(setUsers).catch(() => setUsers([]));
    // Libelles des motifs codes et des allergenes, pour traduire les codes stockes.
    api<Record<string, Option[]>>("approvals/reasons/")
      .then((lists) => setCodes(Object.fromEntries(Object.values(lists).flat().map((o) => [o.code, o.label]))))
      .catch(() => setCodes({}));
    api<{ code: string; name: string }[]>("allergens/")
      .then((list) => setAllergens(Object.fromEntries(list.map((a) => [a.code, a.name]))))
      .catch(() => setAllergens({}));
  }, []);

  function onFilter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const params = new URLSearchParams();
    new FormData(event.currentTarget).forEach((value, key) => {
      if (value) params.set(key, String(value));
    });
    setError(null);
    setPageNumber(1);
    setQuery(params.toString());
  }

  if (error)
    return (
      <main>
        <p role="alert">{error}</p>
        <a href="/">Accueil</a>
      </main>
    );

  return (
    <main>
      <p>
        <a href="/">Accueil</a>
      </p>
      <h1>Journal d&apos;audit</h1>
      <form onSubmit={onFilter} style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 12 }}>
        <select name="entity_type" defaultValue="">
          <option value="">Tous les objets</option>
          {Object.entries(ENTITY_TYPES).map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </select>
        <select name="action" defaultValue="">
          <option value="">Toutes les actions</option>
          {Object.entries(ACTIONS).map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </select>
        <select name="user" defaultValue="">
          <option value="">Tous les utilisateurs</option>
          {users.map((u) => (
            <option key={u.id} value={u.id}>
              {u.username}
            </option>
          ))}
        </select>
        <label>
          Du <input type="date" name="date_from" />
        </label>
        <label>
          au <input type="date" name="date_to" />
        </label>
        <button type="submit">Filtrer</button>
      </form>

      {page === null ? (
        <p>Chargement...</p>
      ) : page.count === 0 ? (
        <p>Aucune entrée.</p>
      ) : (
        <>
          <p>{page.count} entrée(s)</p>
          <table cellPadding={4} style={{ borderCollapse: "collapse", width: "100%" }}>
            <thead>
              <tr style={{ textAlign: "left" }}>
                <th>Date</th>
                <th>Utilisateur</th>
                <th>Action</th>
                <th>Objet</th>
                <th>Détail</th>
              </tr>
            </thead>
            <tbody>
              {page.results.map((e) => (
                <tr key={e.id} style={{ borderTop: "1px solid #ddd", verticalAlign: "top" }}>
                  <td style={{ whiteSpace: "nowrap" }}>{stamp(e.created_at)}</td>
                  <td>{e.username || "(système)"}</td>
                  <td>{ACTIONS[e.action] || e.action}</td>
                  <td>
                    {ENTITY_ONE[e.entity_type] || e.entity_label}
                    {e.subject && (
                      <>
                        <br />
                        <strong>{e.subject}</strong>
                      </>
                    )}
                  </td>
                  <td style={{ overflowWrap: "anywhere" }}>
                    <Changes ctx={{ entry: e, codes, allergens }} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>
            <button disabled={!page.previous} onClick={() => setPageNumber(pageNumber - 1)}>
              Précédent
            </button>{" "}
            Page {pageNumber}{" "}
            <button disabled={!page.next} onClick={() => setPageNumber(pageNumber + 1)}>
              Suivant
            </button>
          </p>
        </>
      )}
    </main>
  );
}
