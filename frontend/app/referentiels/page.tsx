"use client";

// Referentiels (US-02) : liste des articles et des partenaires, import CSV.
// Les regles (allergenes obligatoires, fichier refuse en entier) sont appliquees par l'API.
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

type Article = {
  id: string;
  code: string;
  name: string;
  article_type: string;
  base_unit: string;
  shelf_life_days: number | null;
  storage: string;
  is_active: boolean;
  allergens: Record<string, string> | null;
};
type Partner = {
  id: string;
  name: string;
  is_supplier: boolean;
  is_customer: boolean;
  address: string;
  phone: string;
  email: string;
};
type LineError = { line: number; messages: string[] };
type Allergen = { code: string; name: string };

const PRESENCES: Record<string, string> = { absent: "Absent", peut_contenir: "Peut contenir", contient: "Contient" };
const STORAGES: Record<string, string> = { "": "(non précisé)", ambiant: "Ambiant", refrigere: "Réfrigéré", congele: "Congelé" };

function errorText(body: unknown): string {
  // Erreurs DRF {champ: [messages]} transformees en une phrase lisible.
  if (!body || typeof body !== "object") return "Enregistrement refusé.";
  return Object.entries(body as Record<string, unknown>)
    .map(([field, msgs]) => `${field} : ${Array.isArray(msgs) ? msgs.join(" ") : String(msgs)}`)
    .join(" ");
}

function ArticleEditor({
  article,
  allergens,
  onCancel,
  onSaved,
}: {
  article: Article;
  allergens: Allergen[];
  onCancel: () => void;
  onSaved: () => void;
}) {
  const needsAllergens = article.article_type === "matiere" || article.allergens !== null;
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    const shelfLife = String(form.get("shelf_life_days") || "").trim();
    const payload: Record<string, unknown> = {
      name: String(form.get("name") || "").trim(),
      shelf_life_days: shelfLife ? Number(shelfLife) : null,
      storage: String(form.get("storage") || ""),
      is_active: form.get("is_active") === "on",
    };
    if (needsAllergens) {
      payload.allergens = Object.fromEntries(allergens.map((a) => [a.code, String(form.get(`allergen_${a.code}`))]));
    }
    try {
      await api(`articles/${article.id}/`, { method: "PATCH", body: JSON.stringify(payload) });
      onSaved();
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) setError("Votre rôle ne permet pas de modifier un article.");
      else setError(e instanceof ApiError ? errorText(e.body) : "Erreur pendant l'enregistrement.");
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ display: "grid", gap: 8, padding: 12, border: "1px solid #888", margin: "8px 0" }}>
      <strong>
        Modifier {article.code} (unité de base {article.base_unit}, non modifiable)
      </strong>
      <label>
        Nom <input name="name" defaultValue={article.name} required style={{ width: 320 }} />
      </label>
      <label>
        Durée de vie (jours) <input name="shelf_life_days" type="number" min={1} defaultValue={article.shelf_life_days ?? ""} />
      </label>
      <label>
        Conservation{" "}
        <select name="storage" defaultValue={article.storage}>
          {Object.entries(STORAGES).map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        <input type="checkbox" name="is_active" defaultChecked={article.is_active} /> Actif
      </label>
      {needsAllergens && (
        <fieldset>
          <legend>Allergènes (chacun doit être déclaré)</legend>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 4 }}>
            {allergens.map((a) => (
              <label key={a.code} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <span>{a.name}</span>
                <select name={`allergen_${a.code}`} defaultValue={article.allergens?.[a.code] ?? ""} required>
                  <option value="" disabled>
                    À déclarer
                  </option>
                  {Object.entries(PRESENCES).map(([v, label]) => (
                    <option key={v} value={v}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        </fieldset>
      )}
      {error && <p role="alert">{error}</p>}
      <div>
        <button type="submit">Enregistrer</button> <button type="button" onClick={onCancel}>Annuler</button>
      </div>
    </form>
  );
}

const TYPES: Record<string, string> = {
  matiere: "Matière",
  emballage: "Emballage",
  semi_fini: "Semi-fini",
  fini: "Produit fini",
};

function allergenSummary(a: Article): string {
  if (!a.allergens) return a.article_type === "matiere" ? "Non déclaré" : "";
  const present = Object.entries(a.allergens).filter(([, p]) => p !== "absent");
  if (present.length === 0) return "Aucun";
  return present.map(([code, p]) => (p === "contient" ? code : `${code} (traces)`)).join(", ");
}

function ImportForm({ path, model, onDone }: { path: string; model: string; onDone: () => void }) {
  const [errors, setErrors] = useState<LineError[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setErrors([]);
    setMessage(null);
    const formElement = event.currentTarget;
    try {
      const result = await api<{ created: number }>(path, { method: "POST", body: new FormData(formElement) });
      setMessage(`${result.created} ligne(s) importée(s).`);
      formElement.reset();
      onDone();
    } catch (e) {
      if (e instanceof ApiError && e.status === 400) {
        const body = e.body as { detail?: string; errors?: LineError[] } | null;
        setMessage(body?.detail || "Fichier refusé.");
        setErrors(body?.errors || []);
      } else if (e instanceof ApiError && e.status === 403) {
        setMessage("Votre rôle ne permet pas d'importer.");
      } else {
        setMessage("Erreur pendant l'import.");
      }
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ margin: "12px 0", padding: 12, border: "1px solid #ccc" }}>
      <input type="file" name="file" accept=".csv,text/csv" required /> <button type="submit">Importer</button>{" "}
      <a href={model} download>
        Télécharger le modèle
      </a>
      {message && <p role="status">{message}</p>}
      {errors.length > 0 && (
        <ul>
          {errors.map((err) => (
            <li key={err.line}>
              Ligne {err.line} : {err.messages.join(" ")}
            </li>
          ))}
        </ul>
      )}
    </form>
  );
}

export default function Referentiels() {
  const [articles, setArticles] = useState<Article[] | null>(null);
  const [partners, setPartners] = useState<Partner[] | null>(null);
  const [allergens, setAllergens] = useState<Allergen[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([api<Article[]>("articles/"), api<Partner[]>("partners/")])
      .then(([a, p]) => {
        setArticles(a);
        setPartners(p);
      })
      .catch((e) =>
        setError(e instanceof ApiError && e.status === 403 ? "Connectez-vous, ou votre rôle n'a pas accès." : "Erreur.")
      );
  }, []);

  useEffect(load, [load]);
  useEffect(() => {
    api<Allergen[]>("allergens/").then(setAllergens).catch(() => setAllergens([]));
  }, []);

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
      <h1>Référentiels</h1>

      <h2>Articles</h2>
      <ImportForm path="articles/import/" model="/modeles/articles.csv" onDone={load} />
      {articles === null ? (
        <p>Chargement...</p>
      ) : articles.length === 0 ? (
        <p>Aucun article.</p>
      ) : (
        <table cellPadding={4} style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr style={{ textAlign: "left" }}>
              <th>Code</th>
              <th>Nom</th>
              <th>Type</th>
              <th>Unité</th>
              <th>Durée de vie (j)</th>
              <th>Allergènes</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {articles.map((a) =>
              editing === a.id ? (
                <tr key={a.id}>
                  <td colSpan={7}>
                    <ArticleEditor
                      article={a}
                      allergens={allergens}
                      onCancel={() => setEditing(null)}
                      onSaved={() => {
                        setEditing(null);
                        load();
                      }}
                    />
                  </td>
                </tr>
              ) : (
                <tr key={a.id} style={{ borderTop: "1px solid #ddd", opacity: a.is_active ? 1 : 0.5 }}>
                  <td>{a.code}</td>
                  <td>{a.name}</td>
                  <td>{TYPES[a.article_type] || a.article_type}</td>
                  <td>{a.base_unit}</td>
                  <td>{a.shelf_life_days ?? ""}</td>
                  <td>{allergenSummary(a)}</td>
                  <td>
                    <button onClick={() => setEditing(a.id)}>Modifier</button>
                  </td>
                </tr>
              )
            )}
          </tbody>
        </table>
      )}

      <h2>Fournisseurs et clients</h2>
      <ImportForm path="partners/import/" model="/modeles/partenaires.csv" onDone={load} />
      {partners === null ? (
        <p>Chargement...</p>
      ) : partners.length === 0 ? (
        <p>Aucun partenaire.</p>
      ) : (
        <table cellPadding={4} style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr style={{ textAlign: "left" }}>
              <th>Nom</th>
              <th>Rôle</th>
              <th>Adresse</th>
              <th>Téléphone</th>
              <th>E-mail</th>
            </tr>
          </thead>
          <tbody>
            {partners.map((p) => (
              <tr key={p.id} style={{ borderTop: "1px solid #ddd" }}>
                <td>{p.name}</td>
                <td>{[p.is_supplier && "Fournisseur", p.is_customer && "Client"].filter(Boolean).join(", ")}</td>
                <td>{p.address}</td>
                <td>{p.phone}</td>
                <td>{p.email}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
