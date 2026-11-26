"use client";

// Une personne citee dans un ecran (journal, validations, receptions).
// Responsables (Admin, Qualite, Production) : « Yao Kouassi (op1) », cliquable, ouvre la fiche.
// Operateur et Lecture : l'identifiant seul. L'API refuse l'annuaire (donnees personnelles, minimisation).
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export type DirectoryEntry = { id: string; username: string; full_name: string; job_title_label: string; is_active: boolean };
type Card = DirectoryEntry & {
  role_label: string;
  phone: string;
  email: string;
  manager: { id: string; username: string; full_name: string } | null;
};

// Charge une seule fois par page, partage par toutes les personnes affichees.
let directory: Promise<Map<string, DirectoryEntry> | null> | null = null;
function loadDirectory() {
  if (!directory)
    directory = api<DirectoryEntry[]>("users/directory/")
      .then((rows) => new Map(rows.map((r) => [r.username, r])))
      .catch(() => null); // 403 pour Operateur et Lecture : on affiche l'identifiant seul
  return directory;
}

export function useDirectory() {
  const [people, setPeople] = useState<Map<string, DirectoryEntry> | null>(null);
  useEffect(() => {
    loadDirectory().then(setPeople);
  }, []);
  return people;
}

export const personLabel = (p: DirectoryEntry | undefined, username: string) =>
  p && p.full_name && p.full_name !== username ? `${p.full_name} (${username})` : username;

export function Person({ username }: { username: string | null | undefined }) {
  const people = useDirectory();
  const [open, setOpen] = useState(false);
  if (!username) return <>(système)</>;
  const person = people?.get(username);
  if (!person) return <>{username}</>;
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="Voir la fiche"
        style={{ background: "none", border: "none", padding: 0, color: "#0645ad", textDecoration: "underline", cursor: "pointer", font: "inherit", textAlign: "left" }}
      >
        {personLabel(person, username)}
      </button>
      {open && <PersonCard id={person.id} onClose={() => setOpen(false)} />}
    </>
  );
}

function PersonCard({ id, onClose }: { id: string; onClose: () => void }) {
  const [card, setCard] = useState<Card | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    api<Card>(`users/${id}/`).then(setCard, () => setError(true));
  }, [id]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const row = (label: string, value: string | null | undefined) => (
    <tr>
      <th style={{ textAlign: "left", paddingRight: 12, fontWeight: 500, color: "#555" }}>{label}</th>
      <td>{value || "non renseigné"}</td>
    </tr>
  );
  return (
    <div
      onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,.35)", display: "grid", placeItems: "center", zIndex: 10 }}
    >
      <div
        role="dialog"
        aria-label="Fiche de la personne"
        onClick={(e) => e.stopPropagation()}
        style={{ background: "#fff", padding: 20, borderRadius: 6, minWidth: 300, maxWidth: "calc(100vw - 32px)", textAlign: "left", color: "#000" }}
      >
        {error && <p>Fiche indisponible.</p>}
        {!error && !card && <p>Chargement...</p>}
        {card && (
          <>
            <h3 style={{ marginTop: 0 }}>{card.full_name || card.username}</h3>
            <table cellPadding={3}>
              <tbody>
                {row("Identifiant", card.username)}
                {row("Poste", card.job_title_label)}
                {row("Rôle dans Tracalys", card.role_label)}
                {row("Téléphone pro", card.phone)}
                {row("E-mail pro", card.email)}
                {row("Supérieur", card.manager ? personLabel(card.manager as DirectoryEntry, card.manager.username) : "")}
                {!card.is_active && row("État", "Compte désactivé")}
              </tbody>
            </table>
          </>
        )}
        <p style={{ marginBottom: 0 }}>
          <button type="button" onClick={onClose}>
            Fermer
          </button>
        </p>
      </div>
    </div>
  );
}
