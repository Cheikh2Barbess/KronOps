"use client";

// Referentiels (US-02) : liste des articles et des partenaires, import CSV, filtres combinables.
// Le filtrage et la pagination sont faits par l'API (rapide meme avec des milliers de lignes).
// Les regles (allergenes obligatoires, fichier refuse en entier) sont appliquees par l'API.
import { FormEvent, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

const UNIT_LABEL: Record<string, string> = { kg: "kg", l: "L", unite: "unité(s)" };

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
  city: string;
  contact_name: string;
  phone: string;
  email: string;
  is_active: boolean;
};
type LineError = { line: number; messages: string[] };
type Allergen = { code: string; name: string };

const PRESENCES: Record<string, string> = { absent: "Absent", peut_contenir: "Peut contenir", contient: "Contient" };
const STORAGES: Record<string, string> = { "": "(non précisé)", ambiant: "Ambiant", refrigere: "Réfrigéré", congele: "Congelé" };

function errorText(body: unknown): string {
  // Erreurs DRF {champ: [messages]} transformees en une phrase lisible.
  if (!body || typeof body !== "object") return "Enregistrement refusé.";
  const labels: Record<string, string> = {
    code: "Code", article_type: "Type", base_unit: "Unité", name: "Nom", address: "Adresse", city: "Ville", email: "E-mail", shelf_life_days: "Durée de vie", allergens: "Allergènes",
  };
  return Object.entries(body as Record<string, unknown>)
    .map(([field, msgs]) => {
      const text = Array.isArray(msgs) ? msgs.join(" ") : String(msgs);
      return field === "non_field_errors" || field === "detail" ? text : `${labels[field] || field} : ${text}`;
    })
    .join(" ");
}

function ArticleEditor({
  article,
  allergens,
  onCancel,
  onSaved,
}: {
  article: Article | null; // null = creation d'un nouvel article
  allergens: Allergen[];
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [articleType, setArticleType] = useState(article ? article.article_type : "matiere");
  const needsAllergens = articleType === "matiere" || (article !== null && article.allergens !== null);
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
      if (article) {
        await api(`articles/${article.id}/`, { method: "PATCH", body: JSON.stringify(payload) });
      } else {
        payload.code = String(form.get("code") || "").trim();
        payload.article_type = articleType;
        payload.base_unit = String(form.get("base_unit") || "");
        await api("articles/", { method: "POST", body: JSON.stringify(payload) });
      }
      onSaved();
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) setError("Votre rôle ne permet pas d'enregistrer un article.");
      else setError(e instanceof ApiError ? errorText(e.body) : "Erreur pendant l'enregistrement.");
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ display: "grid", gap: 8, padding: 12, border: "1px solid #888", margin: "8px 0" }}>
      {article ? (
        <strong>
          Modifier {article.code} (unité de base {UNIT_LABEL[article.base_unit] || article.base_unit}, non modifiable)
        </strong>
      ) : (
        <>
          <strong>Nouvel article</strong>
          <label>
            Code <input name="code" required maxLength={50} />
          </label>
          <label>
            Type{" "}
            <select name="article_type" value={articleType} onChange={(e) => setArticleType(e.target.value)}>
              {Object.entries(TYPES).map(([v, label]) => (
                <option key={v} value={v}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Unité de base (non modifiable ensuite){" "}
            <select name="base_unit" defaultValue="kg">
              <option value="kg">kg</option>
              <option value="l">L</option>
              <option value="unite">unité</option>
            </select>
          </label>
        </>
      )}
      <label>
        Nom <input name="name" defaultValue={article?.name ?? ""} required style={{ width: 320 }} />
      </label>
      <label>
        Durée de vie (jours){" "}
        <input name="shelf_life_days" type="number" min={1} defaultValue={article?.shelf_life_days ?? ""} />
      </label>
      <label>
        Conservation{" "}
        <select name="storage" defaultValue={article?.storage ?? ""}>
          {Object.entries(STORAGES).map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        <input type="checkbox" name="is_active" defaultChecked={article?.is_active ?? true} /> Actif
      </label>
      {needsAllergens && (
        <fieldset>
          <legend>Allergènes (chacun doit être déclaré)</legend>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 4 }}>
            {allergens.map((a) => (
              <label key={a.code} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <span>{a.name}</span>
                <select name={`allergen_${a.code}`} defaultValue={article?.allergens?.[a.code] ?? ""} required>
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

// Nom court d'un allergene : « Fruits à coque » plutot que la liste officielle entre parentheses.
const shortName = (name: string) => name.replace(/\s*\(.*\)\s*$/, "");

// Tous les allergenes de l'article, avec leur nom : « contient » en gras, puis les traces.
function AllergenSummary({ article, allergens }: { article: Article; allergens: Allergen[] }) {
  if (!article.allergens) return <>{article.article_type === "emballage" ? "" : "Non déclaré"}</>;
  const name = (code: string) => shortName(allergens.find((x) => x.code === code)?.name || code);
  const entries = Object.entries(article.allergens);
  const contains = entries.filter(([, p]) => p === "contient").map(([c]) => name(c));
  const traces = entries.filter(([, p]) => p === "peut_contenir").map(([c]) => name(c));
  if (contains.length === 0 && traces.length === 0) return <>Aucun</>;
  return (
    <>
      {contains.length > 0 && <strong>Contient : {contains.join(", ")}</strong>}
      {contains.length > 0 && traces.length > 0 && <br />}
      {traces.length > 0 && <em>Traces possibles : {traces.join(", ")}</em>}
    </>
  );
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

function PartnerEditor({
  partner,
  onCancel,
  onSaved,
}: {
  partner: Partner | null; // null = creation
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) || "").trim();
    const payload = {
      name: text("name"),
      is_supplier: form.get("is_supplier") === "on",
      is_customer: form.get("is_customer") === "on",
      address: text("address"),
      city: text("city"),
      contact_name: text("contact_name"),
      phone: text("phone"),
      email: text("email"),
      is_active: form.get("is_active") === "on",
    };
    try {
      if (partner) await api(`partners/${partner.id}/`, { method: "PATCH", body: JSON.stringify(payload) });
      else await api("partners/", { method: "POST", body: JSON.stringify(payload) });
      onSaved();
    } catch (e) {
      if (e instanceof ApiError && e.status === 403) setError("Votre rôle ne permet pas d'enregistrer un partenaire.");
      else setError(e instanceof ApiError ? errorText(e.body) : "Erreur pendant l'enregistrement.");
    }
  }

  return (
    <form onSubmit={onSubmit} style={{ display: "grid", gap: 8, padding: 12, border: "1px solid #888", margin: "8px 0" }}>
      <strong>{partner ? `Modifier ${partner.name}` : "Nouveau fournisseur ou client"}</strong>
      <label>
        Nom <input name="name" defaultValue={partner?.name ?? ""} required style={{ width: 320 }} />
      </label>
      <div>
        <label>
          <input type="checkbox" name="is_supplier" defaultChecked={partner?.is_supplier ?? true} /> Fournisseur
        </label>{" "}
        <label>
          <input type="checkbox" name="is_customer" defaultChecked={partner?.is_customer ?? false} /> Client
        </label>
      </div>
      <label>
        Adresse <textarea name="address" defaultValue={partner?.address ?? ""} required rows={2} style={{ width: 420 }} />
      </label>
      <label>
        Ville <input name="city" defaultValue={partner?.city ?? ""} placeholder="ex. Abidjan" />
      </label>
      <label>
        Contact <input name="contact_name" defaultValue={partner?.contact_name ?? ""} />
      </label>
      <label>
        Téléphone <input name="phone" defaultValue={partner?.phone ?? ""} />
      </label>
      <label>
        E-mail <input name="email" type="email" defaultValue={partner?.email ?? ""} />
      </label>
      <label>
        <input type="checkbox" name="is_active" defaultChecked={partner?.is_active ?? true} /> Actif
      </label>
      {error && <p role="alert">{error}</p>}
      <div>
        <button type="submit">Enregistrer</button> <button type="button" onClick={onCancel}>Annuler</button>
      </div>
    </form>
  );
}

type Page<T> = { count: number; results: T[] };
type City = { city: string; count: number };
const PAGE_SIZE = 50;

// Recharge une liste filtree et paginee. Le texte tape attend 300 ms pour ne pas
// interroger l'API a chaque lettre.
function usePagedList<T>(path: string, filters: Record<string, string>, reloadKey: number) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Page<T> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const query = new URLSearchParams(Object.entries(filters).filter(([, v]) => v !== "")).toString();
  const [debouncedQuery, setDebouncedQuery] = useState(query);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), 300);
    return () => clearTimeout(timer);
  }, [query]);
  useEffect(() => setPage(1), [debouncedQuery]);
  useEffect(() => {
    let cancelled = false;
    const params = `${debouncedQuery}${debouncedQuery ? "&" : ""}page=${page}&page_size=${PAGE_SIZE}`;
    api<Page<T>>(`${path}?${params}`)
      .then((d) => {
        if (!cancelled) {
          setData(d);
          setError(null);
        }
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404 && page > 1) setPage(1);
        else setError(e instanceof ApiError && e.status === 403 ? "Connectez-vous, ou votre rôle n'a pas accès." : "Erreur.");
      });
    return () => {
      cancelled = true;
    };
  }, [path, debouncedQuery, page, reloadKey]);
  return { data, error, page, setPage };
}

function Pager({ count, page, setPage, noun }: { count: number; page: number; setPage: (p: number) => void; noun: string }) {
  const pages = Math.max(1, Math.ceil(count / PAGE_SIZE));
  return (
    <p>
      <strong>{count}</strong> {noun}
      {pages > 1 && (
        <>
          {" "}· page {page} sur {pages}{" "}
          <button disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Précédente
          </button>{" "}
          <button disabled={page >= pages} onClick={() => setPage(page + 1)}>
            Suivante
          </button>
        </>
      )}
    </p>
  );
}

const filterBar = { display: "flex", flexWrap: "wrap" as const, gap: 12, alignItems: "center", padding: 8, background: "#f4f4f4", margin: "8px 0" };

const EMPTY_ARTICLE_FILTERS = { q: "", type: "", storage: "", allergen: "", presence: "present", allergen_free: "", has_allergen: "", active: "" };

function ArticleSection({ allergens }: { allergens: Allergen[] }) {
  const [filters, setFilters] = useState(EMPTY_ARTICLE_FILTERS);
  const [reloadKey, setReloadKey] = useState(0);
  const [editing, setEditing] = useState<string | null>(null);
  const reload = () => setReloadKey((k) => k + 1);
  const apiFilters = { ...filters, presence: filters.allergen ? filters.presence : "" };
  const contains = filters.allergen ? filters.allergen.split(",") : [];
  const free = filters.allergen_free ? filters.allergen_free.split(",") : [];
  const allergenCount = contains.length + free.length + (filters.has_allergen ? 1 : 0);
  // Une case « contient » et « sans » pour le meme allergene s'excluent.
  const toggleAllergen = (key: "allergen" | "allergen_free", code: string) =>
    setFilters((f) => {
      const other = key === "allergen" ? "allergen_free" : "allergen";
      const list = f[key] ? f[key].split(",") : [];
      const next = list.includes(code) ? list.filter((c) => c !== code) : [...list, code];
      const otherList = (f[other] ? f[other].split(",") : []).filter((c) => c !== code);
      return { ...f, [key]: next.join(","), [other]: otherList.join(",") };
    });
  const { data, error, page, setPage } = usePagedList<Article>("articles/", apiFilters, reloadKey);
  const set = (name: keyof typeof EMPTY_ARTICLE_FILTERS) => (e: { target: { value: string } }) =>
    setFilters((f) => ({ ...f, [name]: e.target.value }));
  const types = filters.type ? filters.type.split(",") : [];
  const toggleType = (t: string) =>
    setFilters((f) => ({ ...f, type: (types.includes(t) ? types.filter((x) => x !== t) : [...types, t]).join(",") }));
  const saved = () => {
    setEditing(null);
    reload();
  };

  return (
    <section>
      <h2>Articles</h2>
      {editing === "new" ? (
        <ArticleEditor article={null} allergens={allergens} onCancel={() => setEditing(null)} onSaved={saved} />
      ) : (
        <button onClick={() => setEditing("new")}>Nouvel article</button>
      )}
      <ImportForm path="articles/import/" model="/modeles/articles.csv" onDone={reload} />

      <div style={filterBar} aria-label="Filtres des articles">
        <label>
          Recherche <input name="article_q" value={filters.q} onChange={set("q")} placeholder="code ou nom" />
        </label>
        <span>
          Type :{" "}
          {Object.entries(TYPES).map(([value, label]) => (
            <label key={value} style={{ marginRight: 8 }}>
              <input type="checkbox" name={`type_${value}`} checked={types.includes(value)} onChange={() => toggleType(value)} /> {label}
            </label>
          ))}
        </span>
        <label>
          Conservation{" "}
          <select name="storage" value={filters.storage} onChange={set("storage")}>
            <option value="">Toutes</option>
            {Object.entries(STORAGES).filter(([v]) => v).map(([v, l]) => (
              <option key={v} value={v}>{l}</option>
            ))}
          </select>
        </label>
        <label>
          Statut{" "}
          <select name="article_active" value={filters.active} onChange={set("active")}>
            <option value="">Actifs et inactifs</option>
            <option value="true">Actifs</option>
            <option value="false">Inactifs</option>
          </select>
        </label>
        <button type="button" onClick={() => setFilters(EMPTY_ARTICLE_FILTERS)}>Effacer les filtres</button>
      </div>

      <details style={{ ...filterBar, display: "block" }} open={allergenCount > 0}>
        <summary>
          Allergènes{allergenCount > 0 ? ` (${allergenCount} filtre(s))` : ""}
        </summary>
        <p style={{ margin: "6px 0" }}>
          <label>
            <input type="checkbox" name="has_allergen_true" checked={filters.has_allergen === "true"}
              onChange={(e) => setFilters((f) => ({ ...f, has_allergen: e.target.checked ? "true" : "" }))} />{" "}
            Au moins un allergène
          </label>{" "}
          <label style={{ marginLeft: 12 }}>
            <input type="checkbox" name="has_allergen_false" checked={filters.has_allergen === "false"}
              onChange={(e) => setFilters((f) => ({ ...f, has_allergen: e.target.checked ? "false" : "" }))} />{" "}
            Aucun allergène (articles déclarés)
          </label>
          <label style={{ marginLeft: 12 }}>
            <input type="checkbox" name="with_traces" checked={filters.presence === "present"}
              onChange={(e) => setFilters((f) => ({ ...f, presence: e.target.checked ? "present" : "contient" }))} />{" "}
            Compter aussi les traces (« peut contenir »)
          </label>
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "2px 24px" }}>
          {allergens.map((al) => (
            <div key={al.code} style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span style={{ flex: 1 }} title={al.name}>{shortName(al.name)}</span>
              <label>
                <input type="checkbox" name={`contains_${al.code}`} checked={contains.includes(al.code)}
                  onChange={() => toggleAllergen("allergen", al.code)} /> contient
              </label>
              <label>
                <input type="checkbox" name={`free_${al.code}`} checked={free.includes(al.code)}
                  onChange={() => toggleAllergen("allergen_free", al.code)} /> sans
              </label>
            </div>
          ))}
        </div>
        <p style={{ margin: "6px 0", color: "#555" }}>
          Plusieurs « contient » : l&apos;un ou l&apos;autre. Plusieurs « sans » : aucun d&apos;eux. « Sans » ne retient que les articles dont les allergènes sont déclarés.
        </p>
      </details>

      {error ? (
        <p role="alert">{error}</p>
      ) : data === null ? (
        <p>Chargement...</p>
      ) : (
        <>
          <Pager count={data.count} page={page} setPage={setPage} noun="article(s)" />
          {data.results.length > 0 && (
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
                {data.results.map((a) =>
                  editing === a.id ? (
                    <tr key={a.id}>
                      <td colSpan={7}>
                        <ArticleEditor article={a} allergens={allergens} onCancel={() => setEditing(null)} onSaved={saved} />
                      </td>
                    </tr>
                  ) : (
                    <tr key={a.id} style={{ borderTop: "1px solid #ddd", opacity: a.is_active ? 1 : 0.5 }}>
                      <td>{a.code}</td>
                      <td>{a.name}</td>
                      <td>{TYPES[a.article_type] || a.article_type}</td>
                      <td>{UNIT_LABEL[a.base_unit] || a.base_unit}</td>
                      <td>{a.shelf_life_days ?? ""}</td>
                      <td>
                        <AllergenSummary article={a} allergens={allergens} />
                      </td>
                      <td>
                        <button onClick={() => setEditing(a.id)}>Modifier</button>
                      </td>
                    </tr>
                  )
                )}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}

const EMPTY_PARTNER_FILTERS = { q: "", role: "", city: "", active: "" };

function PartnerSection() {
  const [filters, setFilters] = useState(EMPTY_PARTNER_FILTERS);
  const [reloadKey, setReloadKey] = useState(0);
  const [editing, setEditing] = useState<string | null>(null);
  const [cities, setCities] = useState<City[]>([]);
  const reload = () => setReloadKey((k) => k + 1);
  const { data, error, page, setPage } = usePagedList<Partner>("partners/", filters, reloadKey);
  const set = (name: keyof typeof EMPTY_PARTNER_FILTERS) => (e: { target: { value: string } }) =>
    setFilters((f) => ({ ...f, [name]: e.target.value }));
  useEffect(() => {
    api<City[]>("partners/cities/").then(setCities).catch(() => setCities([]));
  }, [reloadKey]);
  const saved = () => {
    setEditing(null);
    reload();
  };

  return (
    <section>
      <h2>Fournisseurs et clients</h2>
      {editing === "new" ? (
        <PartnerEditor partner={null} onCancel={() => setEditing(null)} onSaved={saved} />
      ) : (
        <button onClick={() => setEditing("new")}>Nouveau fournisseur ou client</button>
      )}
      <ImportForm path="partners/import/" model="/modeles/partenaires.csv" onDone={reload} />

      <div style={filterBar} aria-label="Filtres des fournisseurs et clients">
        <label>
          Recherche <input name="partner_q" value={filters.q} onChange={set("q")} placeholder="nom, contact, adresse" />
        </label>
        <label>
          Rôle{" "}
          <select name="role" value={filters.role} onChange={set("role")}>
            <option value="">Tous</option>
            <option value="supplier">Fournisseurs</option>
            <option value="customer">Clients</option>
            <option value="both">Fournisseurs et clients à la fois</option>
          </select>
        </label>
        <label>
          Ville{" "}
          <select name="city" value={filters.city} onChange={set("city")}>
            <option value="">Toutes</option>
            {cities.map((c) => (
              <option key={c.city} value={c.city}>
                {c.city} ({c.count})
              </option>
            ))}
          </select>
        </label>
        <label>
          Statut{" "}
          <select name="partner_active" value={filters.active} onChange={set("active")}>
            <option value="">Actifs et inactifs</option>
            <option value="true">Actifs</option>
            <option value="false">Inactifs</option>
          </select>
        </label>
        <button type="button" onClick={() => setFilters(EMPTY_PARTNER_FILTERS)}>Effacer les filtres</button>
      </div>

      {error ? (
        <p role="alert">{error}</p>
      ) : data === null ? (
        <p>Chargement...</p>
      ) : (
        <>
          <Pager count={data.count} page={page} setPage={setPage} noun="fournisseur(s) ou client(s)" />
          {data.results.length > 0 && (
            <table cellPadding={4} style={{ borderCollapse: "collapse", width: "100%" }}>
              <thead>
                <tr style={{ textAlign: "left" }}>
                  <th>Nom</th>
                  <th>Rôle</th>
                  <th>Ville</th>
                  <th>Adresse</th>
                  <th>Téléphone</th>
                  <th>E-mail</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((p) =>
                  editing === p.id ? (
                    <tr key={p.id}>
                      <td colSpan={7}>
                        <PartnerEditor partner={p} onCancel={() => setEditing(null)} onSaved={saved} />
                      </td>
                    </tr>
                  ) : (
                    <tr key={p.id} style={{ borderTop: "1px solid #ddd", opacity: p.is_active ? 1 : 0.5 }}>
                      <td>{p.name}</td>
                      <td>{[p.is_supplier && "Fournisseur", p.is_customer && "Client"].filter(Boolean).join(", ")}</td>
                      <td>{p.city}</td>
                      <td>{p.address}</td>
                      <td>{p.phone}</td>
                      <td>{p.email}</td>
                      <td>
                        <button onClick={() => setEditing(p.id)}>Modifier</button>
                      </td>
                    </tr>
                  )
                )}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}

export default function Referentiels() {
  const [allergens, setAllergens] = useState<Allergen[]>([]);
  useEffect(() => {
    api<Allergen[]>("allergens/").then(setAllergens).catch(() => setAllergens([]));
  }, []);

  return (
    <main>
      <p>
        <a href="/">Accueil</a>
      </p>
      <h1>Référentiels</h1>
      <ArticleSection allergens={allergens} />
      <PartnerSection />
    </main>
  );
}
