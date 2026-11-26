"use client";

// Gestion des utilisateurs, reservee a l'Admin (l'API le verifie).
// Poste, role et superieur se choisissent dans des listes. Texte libre seulement pour l'identite
// (nom, prenom, coordonnees professionnelles) et la precision du poste « Autre ».
// Pas d'adresse ni de telephone personnel : minimisation des donnees (loi ivoirienne 2013-450).
// Tout est trace au journal, jamais le mot de passe.
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

type Me = { id: string; username: string; role: string };
type Option = { code: string; label: string };
type Manager = { id: string; username: string; full_name: string };
type User = {
  id: string;
  username: string;
  first_name: string;
  last_name: string;
  full_name: string;
  job_title: string;
  job_title_other: string;
  job_title_label: string;
  phone: string;
  email: string;
  role: string;
  role_label: string;
  manager: Manager | null;
  is_active: boolean;
  last_login: string | null;
};

function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403) return "Réservé à l'administrateur de l'entreprise.";
    if (e.body && typeof e.body === "object" && "detail" in e.body) return String((e.body as { detail: string }).detail);
    if (e.body && typeof e.body === "object")
      return Object.values(e.body as Record<string, unknown>)
        .map((v) => (Array.isArray(v) ? v.join(" ") : String(v)))
        .join(" ");
  }
  return "Erreur.";
}

const who = (u: { full_name: string; username: string }) =>
  u.full_name && u.full_name !== u.username ? `${u.full_name} (${u.username})` : u.username;

function UserForm({
  user,
  users,
  jobs,
  roles,
  me,
  onDone,
}: {
  user: User | null;
  users: User[];
  jobs: Option[];
  roles: Option[];
  me: Me;
  onDone: (message: string) => void;
}) {
  const [job, setJob] = useState(user?.job_title || "");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");
  const self = user?.id === me.id;
  // Superieur possible : un compte actif, ni la personne elle-meme.
  const managers = users.filter((u) => u.is_active && u.id !== user?.id);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError("");
    setSaved("");
    const f = new FormData(e.currentTarget);
    const body: Record<string, unknown> = {
      first_name: f.get("first_name"),
      last_name: f.get("last_name"),
      job_title: f.get("job_title"),
      job_title_other: job === "autre" ? f.get("job_title_other") : "",
      phone: f.get("phone"),
      email: f.get("email"),
      role: f.get("role"),
      manager: f.get("manager") || null,
    };
    if (!user) body.username = f.get("username");
    if (f.get("password")) body.password = f.get("password");
    if (user && !self) body.is_active = f.get("is_active") === "on";
    try {
      if (user) await api(`users/${user.id}/`, { method: "PATCH", body: JSON.stringify(body) });
      else await api("users/", { method: "POST", body: JSON.stringify(body) });
      setSaved("Modifications enregistrées.");
      onDone(user ? "" : `Utilisateur ${body.username} créé.`);
    } catch (err) {
      setError(errorText(err));
    }
  }

  return (
    <form key={user?.id || "new"} onSubmit={onSubmit} style={{ display: "grid", gap: 8, maxWidth: 480, border: "1px solid #ccc", padding: 12 }}>
      <h3 style={{ margin: 0 }}>{user ? `Modifier ${who(user)}` : "Nouvel utilisateur"}</h3>
      <label>
        Identifiant de connexion{" "}
        {user ? <strong>{user.username}</strong> : <input name="username" required autoComplete="off" />}
      </label>
      {user && <small>L&apos;identifiant ne change pas : il est cité dans tout le journal.</small>}
      <label>
        Prénom <input name="first_name" defaultValue={user?.first_name} required />
      </label>
      <label>
        Nom <input name="last_name" defaultValue={user?.last_name} required />
      </label>
      <label>
        Poste{" "}
        <select name="job_title" value={job} onChange={(e) => setJob(e.target.value)} required>
          <option value="">Choisir...</option>
          {jobs.map((o) => (
            <option key={o.code} value={o.code}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      {job === "autre" && (
        <label>
          Préciser le poste <input name="job_title_other" defaultValue={user?.job_title_other} required />
        </label>
      )}
      <label>
        Téléphone professionnel <input name="phone" type="tel" defaultValue={user?.phone} />
      </label>
      <label>
        E-mail professionnel <input name="email" type="email" defaultValue={user?.email} />
      </label>
      <label>
        Rôle dans Tracalys{" "}
        <select name="role" defaultValue={user?.role || ""} required disabled={self}>
          <option value="">Choisir...</option>
          {roles.map((o) => (
            <option key={o.code} value={o.code}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      {self && (
        <>
          <input type="hidden" name="role" value={user!.role} />
          <small>Vous ne pouvez pas retirer votre propre rôle d&apos;administrateur.</small>
        </>
      )}
      <label>
        Supérieur{" "}
        <select name="manager" defaultValue={user?.manager?.id || ""}>
          <option value="">Aucun</option>
          {managers.map((u) => (
            <option key={u.id} value={u.id}>
              {who(u)}
              {u.job_title_label && ` · ${u.job_title_label}`}
            </option>
          ))}
        </select>
      </label>
      <label>
        {user ? "Nouveau mot de passe (laisser vide pour ne pas changer)" : "Mot de passe"}{" "}
        <input name="password" type="password" autoComplete="new-password" required={!user} minLength={10} />
      </label>
      <small>10 caractères au moins, pas un mot de passe courant, pas seulement des chiffres.</small>
      {user && !self && (
        <label>
          <input type="checkbox" name="is_active" defaultChecked={user.is_active} /> Compte actif (décocher pour
          désactiver : la personne ne peut plus se connecter, son historique reste)
        </label>
      )}
      <button type="submit">{user ? "Enregistrer" : "Créer l'utilisateur"}</button>
      {saved && <p>{saved}</p>}
      {error && <p role="alert">{error}</p>}
    </form>
  );
}

export default function Users() {
  const [me, setMe] = useState<Me | null>(null);
  const [users, setUsers] = useState<User[] | null>(null);
  const [jobs, setJobs] = useState<Option[]>([]);
  const [roles, setRoles] = useState<Option[]>([]);
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const reload = useCallback(() => {
    api<User[]>("users/").then(setUsers, (e) => setError(errorText(e)));
  }, []);

  useEffect(() => {
    api<Me>("auth/me/").then(setMe, () => setError("Connectez-vous d'abord."));
    api<{ job_titles: Option[]; roles: Option[] }>("users/options/").then((o) => {
      setJobs(o.job_titles);
      setRoles(o.roles);
    }, () => undefined);
    reload();
  }, [reload]);

  if (error) {
    return (
      <main>
        <p>
          <a href="/">Accueil</a>
        </p>
        <p role="alert">{error}</p>
      </main>
    );
  }
  if (!me || !users) return <main>Chargement...</main>;
  const current = editing && editing !== "new" ? users.find((u) => u.id === editing) || null : null;

  return (
    <main>
      <p>
        <a href="/">Accueil</a>
      </p>
      <h1>Utilisateurs</h1>
      <p>
        Fiches visibles par l&apos;Admin, la Qualité et la Production. Les opérateurs et le rôle Lecture ne voient que
        les identifiants. Chaque création ou modification est tracée au journal, jamais le mot de passe.
      </p>
      <p>
        <button onClick={() => { setNotice(""); setEditing("new"); }}>Ajouter un utilisateur</button>
      </p>
      {notice && <p>{notice}</p>}
      {editing && (
        <UserForm
          key={editing}
          user={current}
          users={users}
          jobs={jobs}
          roles={roles}
          me={me}
          onDone={(message) => {
            reload();
            if (message) {
              setNotice(message);
              setEditing(null);
            }
          }}
        />
      )}
      <table cellPadding={4} style={{ borderCollapse: "collapse", width: "100%", marginTop: 16 }}>
        <thead>
          <tr style={{ textAlign: "left" }}>
            <th>Nom</th>
            <th>Poste</th>
            <th>Rôle</th>
            <th>Supérieur</th>
            <th>Coordonnées pro</th>
            <th>État</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} style={{ borderTop: "1px solid #ddd", verticalAlign: "top", color: u.is_active ? undefined : "#888" }}>
              <td>{who(u)}</td>
              <td>{u.job_title_label}</td>
              <td>{u.role_label}</td>
              <td>{u.manager ? who(u.manager) : ""}</td>
              <td>
                {u.phone}
                {u.phone && u.email && <br />}
                {u.email}
              </td>
              <td>{u.is_active ? "Actif" : "Désactivé"}</td>
              <td>
                <button onClick={() => setEditing(u.id)}>Modifier</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
