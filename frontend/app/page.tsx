"use client";

// Accueil. Connecte : la zone de droite reste vide, le menu de gauche ouvre les ecrans.
// Plus tard, un tableau de bord s'ouvrira ici par defaut.
// Pas connecte : formulaire de connexion. Il ne s'affiche qu'une fois la session verifiee,
// pour ne pas le montrer a un utilisateur deja connecte.
import { FormEvent, useState } from "react";
import { Me, useSession } from "@/components/AppShell";
import { api, ApiError } from "@/lib/api";

export default function Home() {
  const { me, setMe } = useSession();
  const [error, setError] = useState<string | null>(null);

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

  if (me === undefined) return <p>Vérification de la session...</p>;
  if (me) return null;
  return (
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
  );
}
