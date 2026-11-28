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
const box = { display: "grid", gap: 8, padding: 12, border: "1px solid var(--line)", borderRadius: "var(--radius)", background: "var(--surface)", margin: "8px 0", maxWidth: 640 };

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
      <small style={{ color: "var(--muted)" }}>
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
        <table cellPadding={4} style={{ width: "100%" }}>
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
                <tr key={p.id} style={{ opacity: p.is_active ? 1 : 0.5 }}>
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
      <p style={{ color: "var(--muted)" }}>
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
      <table cellPadding={4} style={{ width: "100%" }}>
        <tbody>
          {rows.map((e) =>
            editing === e.id ? (
              <tr key={e.id}>
                <td colSpan={5}>
                  <EquipmentEditor item={e} sites={sites} onDone={done} />
                </td>
              </tr>
            ) : (
              <tr key={e.id} style={{ opacity: e.is_active ? 1 : 0.5 }}>
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

type StepRow = { code: string; label: string; is_active: boolean; position: number };

// Etapes de production de l'entreprise : liste fermee (pas de texte libre), activable et ordonnable.
// Seul l'Admin enregistre (verifie par l'API). Une etape desactivee disparait de l'ecran de declaration.
export function StepSection() {
  const [rows, setRows] = useState<StepRow[]>([]);
  const [isAdmin, setIsAdmin] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    api<StepRow[]>("production/steps/").then(setRows).catch(() => setRows([]));
  }, []);
  useEffect(load, [load]);
  useEffect(() => {
    api<{ role: string }>("auth/me/")
      .then((me) => setIsAdmin(me.role === "admin"))
      .catch(() => setIsAdmin(false));
  }, []);

  function toggle(code: string) {
    setMessage(null);
    setRows((current) => current.map((r) => (r.code === code ? { ...r, is_active: !r.is_active } : r)));
  }
  function move(index: number, delta: number) {
    setMessage(null);
    setRows((current) => {
      const target = index + delta;
      if (target < 0 || target >= current.length) return current;
      const next = [...current];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }
  async function save() {
    setError(null);
    setMessage(null);
    try {
      const saved = await api<StepRow[]>("production/steps/", {
        method: "PUT",
        body: JSON.stringify({ steps: rows.map((r) => ({ code: r.code, is_active: r.is_active })) }),
      });
      setRows(saved);
      setMessage("Étapes enregistrées.");
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <section>
      <h2>Étapes de production</h2>
      <p style={{ color: "var(--muted)", maxWidth: 640 }}>
        Cochez les étapes que vos équipes déclarent, dans l'ordre de votre procédé. Une étape décochée n'est plus
        proposée à la déclaration. Les déclarations déjà faites restent dans l'historique.
      </p>
      <table cellPadding={4}>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.code} style={{ opacity: r.is_active ? 1 : 0.6 }}>
              <td>
                <label>
                  <input type="checkbox" checked={r.is_active} disabled={!isAdmin} onChange={() => toggle(r.code)} />{" "}
                  {r.label}
                </label>
              </td>
              {isAdmin && (
                <td>
                  <button type="button" aria-label={`Monter ${r.label}`} disabled={i === 0} onClick={() => move(i, -1)}>
                    ↑
                  </button>{" "}
                  <button
                    type="button"
                    aria-label={`Descendre ${r.label}`}
                    disabled={i === rows.length - 1}
                    onClick={() => move(i, 1)}
                  >
                    ↓
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {isAdmin ? (
        <p>
          <button type="button" onClick={save}>
            Enregistrer les étapes
          </button>
        </p>
      ) : (
        <p style={{ color: "var(--muted)" }}>Seul l'administrateur de l'entreprise peut modifier les étapes.</p>
      )}
      {message && <p role="status">{message}</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}

type RouteRow = {
  id: string;
  name: string;
  is_active: boolean;
  steps: { code: string; label: string }[];
  articles: { id: string; code: string; name: string }[];
};
type RouteArticleOption = { id: string; code: string; name: string };

function RouteEditor({
  route,
  steps,
  articles,
  routes,
  onDone,
}: {
  route: RouteRow | null;
  steps: StepRow[];
  articles: RouteArticleOption[];
  routes: RouteRow[];
  onDone: () => void;
}) {
  const [name, setName] = useState(route?.name || "");
  const [active, setActive] = useState(route ? route.is_active : true);
  const [chosenSteps, setChosenSteps] = useState<string[]>(route ? route.steps.map((s) => s.code) : []);
  const [chosenArticles, setChosenArticles] = useState<string[]>(route ? route.articles.map((a) => a.id) : []);
  const [error, setError] = useState<string | null>(null);
  // Article deja rattache a un autre parcours : affiche mais non cochable.
  const elsewhere: Record<string, string> = {};
  routes.filter((r) => r.id !== route?.id).forEach((r) => r.articles.forEach((a) => (elsewhere[a.id] = r.name)));
  const flip = (list: string[], value: string) => (list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  const labelOf: Record<string, string> = Object.fromEntries(steps.map((s) => [s.code, s.label]));
  const move = (list: string[], i: number, delta: number) => {
    const next = [...list];
    [next[i], next[i + delta]] = [next[i + delta], next[i]];
    return next;
  };

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const body = JSON.stringify({ name, is_active: active, steps: chosenSteps, articles: chosenArticles });
    try {
      if (route) await api(`production/routes/${route.id}/`, { method: "PUT", body });
      else await api("production/routes/", { method: "POST", body });
      onDone();
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <form onSubmit={onSubmit} style={box}>
      <label>
        Nom du parcours <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={100} placeholder="Mangue séchée" />
      </label>
      {route && (
        <label>
          <input type="checkbox" checked={active} onChange={() => setActive(!active)} /> Parcours actif
        </label>
      )}
      <fieldset>
        <legend>Étapes du parcours, dans l&apos;ordre du procédé de ce produit</legend>
        {/* Etapes cochees d'abord, dans l'ordre du parcours (fleches), puis les autres etapes actives. */}
        {chosenSteps.map((code, i) => (
          <div key={code} style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <label>
              <input type="checkbox" checked onChange={() => setChosenSteps(flip(chosenSteps, code))} /> {i + 1}. {labelOf[code] || code}
            </label>
            <button type="button" aria-label={`Monter ${labelOf[code]}`} disabled={i === 0} onClick={() => setChosenSteps(move(chosenSteps, i, -1))}>
              ↑
            </button>
            <button
              type="button"
              aria-label={`Descendre ${labelOf[code]}`}
              disabled={i === chosenSteps.length - 1}
              onClick={() => setChosenSteps(move(chosenSteps, i, 1))}
            >
              ↓
            </button>
          </div>
        ))}
        {steps
          .filter((s) => s.is_active && !chosenSteps.includes(s.code))
          .map((s) => (
            <label key={s.code} style={{ display: "block", color: "var(--muted)" }}>
              <input type="checkbox" checked={false} onChange={() => setChosenSteps([...chosenSteps, s.code])} /> {s.label}
            </label>
          ))}
      </fieldset>
      <fieldset>
        <legend>Articles qui suivent ce parcours</legend>
        {articles.map((a) => (
          <label key={a.id} style={{ display: "block", color: elsewhere[a.id] ? "var(--muted)" : undefined }}>
            <input
              type="checkbox"
              checked={chosenArticles.includes(a.id)}
              disabled={!!elsewhere[a.id]}
              onChange={() => setChosenArticles(flip(chosenArticles, a.id))}
            />{" "}
            {a.code} {a.name}
            {elsewhere[a.id] ? ` (déjà dans « ${elsewhere[a.id]} »)` : ""}
          </label>
        ))}
      </fieldset>
      <div>
        <button type="submit">Enregistrer le parcours</button>{" "}
        <button type="button" onClick={onDone}>
          Annuler
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
    </form>
  );
}

// Parcours par produit : la mangue et la coco n'ont pas les memes etapes. Un article sans parcours suit les
// etapes actives de l'entreprise. Seul l'Admin cree ou modifie un parcours (verifie par l'API).
export function RouteSection() {
  const [routes, setRoutes] = useState<RouteRow[]>([]);
  const [steps, setSteps] = useState<StepRow[]>([]);
  const [articles, setArticles] = useState<RouteArticleOption[]>([]);
  const [isAdmin, setIsAdmin] = useState(false);
  const [editing, setEditing] = useState<RouteRow | "new" | null>(null);
  const load = useCallback(() => {
    api<RouteRow[]>("production/routes/").then(setRoutes).catch(() => setRoutes([]));
    api<StepRow[]>("production/steps/").then(setSteps).catch(() => setSteps([]));
  }, []);
  useEffect(load, [load]);
  useEffect(() => {
    api<{ role: string }>("auth/me/")
      .then((me) => {
        const admin = me.role === "admin";
        setIsAdmin(admin);
        if (admin)
          api<{ output_articles: RouteArticleOption[] }>("production/runs/options/")
            .then((o) => setArticles(o.output_articles))
            .catch(() => setArticles([]));
      })
      .catch(() => setIsAdmin(false));
  }, []);

  return (
    <section>
      <h2>Parcours par produit</h2>
      <p style={{ color: "var(--muted)", maxWidth: 640 }}>
        Un parcours dit quelles étapes un produit traverse et dans quel ordre (par exemple, la coco est cassée et
        parée avant le lavage, la mangue n&apos;a pas de cassage). À la déclaration, on choisit le produit et ses étapes
        s&apos;affichent dans l&apos;ordre de son parcours. Un article sans parcours suit les étapes actives de l&apos;entreprise.
      </p>
      <table cellPadding={4}>
        <thead>
          <tr>
            <th align="left">Parcours</th>
            <th align="left">Étapes</th>
            <th align="left">Articles</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {routes.map((r) => (
            <tr key={r.id} style={{ opacity: r.is_active ? 1 : 0.6 }}>
              <td>
                {r.name}
                {!r.is_active && " (désactivé)"}
              </td>
              <td>{r.steps.map((s, i) => `${i + 1}. ${s.label}`).join(" → ")}</td>
              <td>{r.articles.map((a) => a.code).join(", ")}</td>
              <td>
                {isAdmin && (
                  <button type="button" onClick={() => setEditing(r)}>
                    Modifier
                  </button>
                )}
              </td>
            </tr>
          ))}
          {routes.length === 0 && (
            <tr>
              <td colSpan={4}>Aucun parcours : tous les articles suivent les étapes actives de l&apos;entreprise.</td>
            </tr>
          )}
        </tbody>
      </table>
      {isAdmin && editing === null && (
        <p>
          <button type="button" onClick={() => setEditing("new")}>
            + Nouveau parcours
          </button>
        </p>
      )}
      {isAdmin && editing !== null && (
        <RouteEditor
          key={editing === "new" ? "new" : editing.id}
          route={editing === "new" ? null : editing}
          steps={steps}
          articles={articles}
          routes={routes}
          onDone={() => {
            setEditing(null);
            load();
          }}
        />
      )}
    </section>
  );
}
