"use client";

// Seuils des couleurs du tableau de bord (Admin). Chaque seuil part d'une valeur par defaut proposee par
// Tracalys, signalee comme telle. L'entreprise la remplace par la sienne, ou y revient. Tout est au journal.
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useSession } from "@/components/AppShell";
import { errorText } from "@/components/Codes";
import { StatusBadge } from "@/components/Status";
import { api } from "@/lib/api";
import { Threshold, thresholdText } from "@/lib/thresholds";

type Row = Threshold & { help: string; default_green: string; default_red: string };
const num = (n: string | number) => Number(n).toLocaleString("fr-FR", { maximumFractionDigits: 2 });

export default function Seuils() {
  const { me } = useSession();
  const [rows, setRows] = useState<Row[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Row[]>("dashboard/thresholds/").then(setRows).catch((e) => setError(errorText(e)));
  }, []);

  function replace(row: Row) {
    setRows((old) => old.map((r) => (r.code === row.code ? row : r)));
  }

  async function onSave(event: FormEvent<HTMLFormElement>, code: string) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    const form = new FormData(event.currentTarget);
    const value = (k: string) => String(form.get(k) || "").replace(",", ".");
    try {
      const row = await api<Row>(`dashboard/thresholds/${code}/`, { method: "PUT", body: JSON.stringify({ green: value("green"), red: value("red") }) });
      replace(row);
      setMessage(`Seuil « ${row.label} » enregistré.`);
    } catch (e) {
      setError(errorText(e));
    }
  }

  async function onReset(code: string) {
    setError(null);
    try {
      const row = await api<Row>(`dashboard/thresholds/${code}/`, { method: "DELETE" });
      replace(row);
      setMessage(`Seuil « ${row.label} » revenu à la valeur par défaut.`);
    } catch (e) {
      setError(errorText(e));
    }
  }

  if (!me) return null;
  if (me.role !== "admin") return <p>Réservé à l&apos;administrateur de l&apos;entreprise.</p>;
  return (
    <main>
      <p>
        <Link href="/dashboard">← Retour au tableau de bord</Link>
      </p>
      <h1>Seuils des couleurs</h1>
      <p>
        Chaque indicateur passe au <StatusBadge status="ok" />, au <StatusBadge status="warn" /> ou au <StatusBadge status="bad" /> selon
        deux seuils. Les valeurs proposées au départ sont des <strong>valeurs par défaut</strong> de Tracalys, sans norme officielle
        derrière : réglez-les selon vos objectifs. Chaque changement est inscrit au journal d&apos;audit.
      </p>
      {message && <p style={{ background: "#e8f5e9", padding: 8 }}>{message}</p>}
      {error && <p role="alert">{error}</p>}
      <div style={{ display: "grid", gap: 12, maxWidth: 900 }}>
        {rows.map((r) => (
          <form key={`${r.code}-${r.green}-${r.red}`} onSubmit={(e) => onSave(e, r.code)} style={{ border: "1px solid var(--line)", borderRadius: 8, padding: 12, display: "grid", gap: 8 }}>
            <strong>
              {r.label}{" "}
              {r.is_default ? <StatusBadge status="info" text="Valeur par défaut" /> : <StatusBadge status="ok" text="Réglé par l'entreprise" />}
            </strong>
            <small style={{ color: "#4b5563" }}>
              {r.help} {r.direction === "higher" ? "Plus c'est haut, mieux c'est." : "Plus c'est bas, mieux c'est."}
            </small>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center" }}>
              <label>
                {r.direction === "higher" ? "Vert à partir de" : "Vert jusqu'à"}{" "}
                <input name="green" type="number" step="0.01" defaultValue={Number(r.green)} required style={{ width: 90 }} /> {r.unit}
              </label>
              <label>
                {r.direction === "higher" ? "Rouge en dessous de" : "Rouge au-delà de"}{" "}
                <input name="red" type="number" step="0.01" defaultValue={Number(r.red)} required style={{ width: 90 }} /> {r.unit}
              </label>
              <button type="submit">Enregistrer</button>
              {!r.is_default && (
                <button type="button" onClick={() => onReset(r.code)}>
                  Revenir au défaut ({num(r.default_green)} et {num(r.default_red)} {r.unit})
                </button>
              )}
            </div>
            <small>Règle actuelle : {thresholdText(r)}.</small>
          </form>
        ))}
      </div>
    </main>
  );
}
