"use client";

// Page de demonstration du socle : etat du service, connexion, utilisateur courant.
// Lien vers les referentiels une fois connecte. Le formulaire de connexion ne
// s'affiche qu'une fois la session verifiee, pour ne pas le montrer a un utilisateur deja connecte.
import { FormEvent, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

type Me = { username: string; role: string; tenant_name: string };
type Health = { status: string; database: string };
type PipelineBlock = { steps: { code: string; is_active: boolean }[] };

export default function Home() {
  const [health, setHealth] = useState<Health | null>(null);
  // undefined = on ne sait pas encore (verification en cours), null = pas connecte.
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  // Modules facultatifs desactives dans l'ecran Pipeline : leur lien n'est pas affiche.
  const [off, setOff] = useState<string[]>([]);

  useEffect(() => {
    api<Health>("health/").then(setHealth).catch(() => setHealth({ status: "injoignable", database: "?" }));
    api<Me>("auth/me/").then(setMe).catch(() => setMe(null));
  }, []);
  useEffect(() => {
    if (!me) return;
    api<PipelineBlock[]>("production/pipeline/")
      .then((blocks) => setOff(blocks.flatMap((b) => b.steps).filter((s) => !s.is_active).map((s) => s.code)))
      .catch(() => setOff([]));
  }, [me]);

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
      <h1>Tracalys</h1>
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
            <a href="/referentiels">Référentiels : articles, fournisseurs, clients, parcelles, sites et équipements</a>
          </p>
          <p>
            <a href="/pipeline">Pipeline : les 8 blocs, du producteur au conteneur</a>
          </p>
          {["admin", "qualite", "production", "lecture"].includes(me.role) && (
            <p>
              <a href="/tracabilite">Traçabilité : recherche amont et aval</a>
            </p>
          )}
          {["admin", "qualite", "production", "operateur"].includes(me.role) && (
            <p>
              <a href="/receptions">Réceptions : enregistrer une livraison</a>
            </p>
          )}
          {["admin", "production", "operateur"].includes(me.role) && (
            <p>
              <a href="/production">Production : déclarer une étape (mûrissement, séchage, cartons, palette)</a>
            </p>
          )}
          {["admin", "production", "operateur"].includes(me.role) && !off.includes("transfert") && (
            <p>
              <a href="/transferts">Transferts : envoyer un lot vers une autre usine</a>
            </p>
          )}
          {["admin", "qualite"].includes(me.role) && (
            <p>
              <a href="/qualite">Contrôle qualité d&apos;un lot</a>
            </p>
          )}
          {["admin", "production"].includes(me.role) && !off.includes("expedition") && (
            <p>
              <a href="/expeditions">Expéditions : conteneur, plomb, certificat d&apos;inspection</a>
            </p>
          )}
          {["admin", "qualite", "production", "lecture"].includes(me.role) && (
            <>
              <p>
                <a href="/bilan">Bilan matière : rendements et écarts</a>
              </p>
              <p>
                <a href="/rappel">Rapport de rappel depuis un carton, une palette ou un conteneur</a>
              </p>
            </>
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
          {me.role === "admin" && (
            <p>
              <a href="/utilisateurs">Utilisateurs : créer, modifier, désactiver</a>
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
