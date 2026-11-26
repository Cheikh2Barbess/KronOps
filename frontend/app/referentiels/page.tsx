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
            </tr>
          </thead>
          <tbody>
            {articles.map((a) => (
              <tr key={a.id} style={{ borderTop: "1px solid #ddd", opacity: a.is_active ? 1 : 0.5 }}>
                <td>{a.code}</td>
                <td>{a.name}</td>
                <td>{TYPES[a.article_type] || a.article_type}</td>
                <td>{a.base_unit}</td>
                <td>{a.shelf_life_days ?? ""}</td>
                <td>{allergenSummary(a)}</td>
              </tr>
            ))}
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
