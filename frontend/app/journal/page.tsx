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
};
type Page = { count: number; next: string | null; previous: string | null; results: Entry[] };
type AuditUser = { id: string; username: string };

const ACTIONS: Record<string, string> = {
  create: "Création",
  update: "Modification",
  import: "Import",
  cancel: "Annulation",
};
const ENTITY_TYPES: Record<string, string> = {
  "catalog.article": "Articles",
  "catalog.partner": "Fournisseurs et clients",
  "catalog.unitconversion": "Conversions d'unités",
  "tenants.site": "Sites",
};

// Libelles francais des champs enregistres dans le journal.
const FIELDS: Record<string, string> = {
  code: "code",
  name: "nom",
  article_type: "type",
  base_unit: "unité",
  shelf_life_days: "durée de vie (j)",
  storage: "conservation",
  is_active: "actif",
  allergens: "allergènes",
  is_supplier: "fournisseur",
  is_customer: "client",
  address: "adresse",
  contact_name: "contact",
  phone: "téléphone",
  email: "e-mail",
  unit_name: "unité",
  factor: "facteur",
};
const label = (field: string) => FIELDS[field] || field;

function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "(vide)";
  if (typeof value === "boolean") return value ? "oui" : "non";
  if (typeof value === "object") {
    // Ex. allergenes a la creation : on ne liste que ceux qui ne sont pas absents.
    const present = Object.entries(value as Record<string, unknown>).filter(([, v]) => v !== "absent");
    return present.length ? present.map(([k, v]) => `${k} ${String(v)}`).join(", ") : "aucun";
  }
  return String(value);
}

function Changes({ entry }: { entry: Entry }) {
  const oldV = entry.old_values || {};
  const newV = entry.new_values || {};
  if (entry.changed_fields.length === 0) {
    // Creation ou import : on montre les valeurs saisies.
    return (
      <span>
        {Object.entries(newV)
          .filter(([, v]) => v !== null && v !== "")
          .map(([k, v]) => `${label(k)} = ${show(v)}`)
          .join(" · ")}
      </span>
    );
  }
  return (
    <ul style={{ margin: 0, paddingLeft: 16 }}>
      {entry.changed_fields.map((field) => {
        const before = oldV[field];
        const after = newV[field];
        if (before && after && typeof before === "object" && typeof after === "object") {
          // Ex. allergenes : on ne montre que les cles qui changent.
          const b = before as Record<string, unknown>;
          const a = after as Record<string, unknown>;
          const keys = Object.keys({ ...b, ...a }).filter((k) => b[k] !== a[k]);
          return (
            <li key={field}>
              {label(field)} : {keys.map((k) => `${k} ${show(b[k])} → ${show(a[k])}`).join(", ")}
            </li>
          );
        }
        return (
          <li key={field}>
            {label(field)} : {show(before)} → {show(after)}
          </li>
        );
      })}
    </ul>
  );
}

export default function Journal() {
  const [page, setPage] = useState<Page | null>(null);
  const [users, setUsers] = useState<AuditUser[]>([]);
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
                  <td style={{ whiteSpace: "nowrap" }}>{new Date(e.created_at).toLocaleString("fr-FR")}</td>
                  <td>{e.username || "(système)"}</td>
                  <td>{ACTIONS[e.action] || e.action}</td>
                  <td>
                    {e.entity_label}
                    {typeof e.new_values?.code === "string" ? ` ${e.new_values.code}` : ""}
                    {typeof e.new_values?.name === "string" ? ` ${e.new_values.name}` : ""}
                  </td>
                  <td style={{ overflowWrap: "anywhere" }}>
                    <Changes entry={e} />
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
