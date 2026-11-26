"use client";

// Page de demonstration du socle : etat du service, connexion, utilisateur courant.
// Lien vers les referentiels une fois connecte. Le formulaire de connexion ne
// s'affiche qu'une fois la session verifiee, pour ne pas le montrer a un utilisateur deja connecte.
import { FormEvent, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

type Me = { username: string; role: string; tenant_name: string };
type Health = { status: string; database: string };

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  // undefined = on ne sait pas encore (verification en cours), null = pas connecte.
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Health>("health/").then(setHealth).catch(() => setHealth({ status: "injoignable", database: "?" }));
    api<Me>("auth/me/").then(setMe).catch(() => setMe(null));
  }, []);

  async function onLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    try {
      const user = await api<Me>("auth/login/", {
        method: "POST",
        body: JSON.stringify({ username: form.get("username"), password: form.get("password") }),
      });
      setMe(user);
    } catch (e) {
      setError(e instanceof ApiError && e.status === 400 ? "Identifiants invalides." : "Erreur de connexion.");
    }
  }

  async function onLogout() {
    await api("auth/logout/", { method: "POST" });
    setMe(null);
  }

  return (
    <main>
      <h1>KronOps</h1>
      <p>
        Service : <strong>{health ? health.status : "..."}</strong> · Base de données :{" "}
        <strong>{health ? health.database : "..."}</strong>
      </p>
      {me === undefined ? (
        <p>Vérification de la session...</p>
      ) : me ? (
        <section>
          <p>
            Connecté : <strong>{me.username}</strong> ({me.role}) chez <strong>{me.tenant_name}</strong>
          </p>
          <p>
            <a href="/referentiels">Référentiels : articles, fournisseurs et clients</a>
          </p>
          {["admin", "qualite", "production", "lecture"].includes(me.role) && (
            <p>
              <a href="/tracabilite">Traçabilité : recherche amont et aval</a>
            </p>
          )}
          {["admin", "qualite", "production", "operateur"].includes(me.role) && (
            <p>
              <a href="/validations">Validations : déblocage, destruction, rebut, ajustement</a>
            </p>
          )}
          {["admin", "qualite"].includes(me.role) && (
            <p>
              <a href="/journal">Journal d&apos;audit</a>
            </p>
          )}
          <button onClick={onLogout}>Se déconnecter</button>
        </section>
      ) : (
        <form onSubmit={onLogin} style={{ display: "grid", gap: 8, maxWidth: 320 }}>
          <label>
            Identifiant <input name="username" autoComplete="username" required />
          </label>
          <label>
            Mot de passe <input name="password" type="password" autoComplete="current-password" required />
          </label>
          <button type="submit">Se connecter</button>
          {error && <p role="alert">{error}</p>}
        </form>
      )}
    </main>
  );
}
