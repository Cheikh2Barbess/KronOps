"use client";

// Cibles de production (Sollwert), saisies par l'Admin : une quantite par produit et par mois, en unite de base.
// Le tableau de bord les compare au reel (Istwert) tire des declarations d'etape. Case vide = pas de cible ce mois-la.
// Chaque changement passe au journal d'audit, avec un motif choisi dans une liste quand une cible deja saisie change.
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { useSession } from "@/components/AppShell";
import { CodePicker, Option, errorText, unitLabel } from "@/components/Codes";
import { api } from "@/lib/api";

type Row = { id: string; code: string; name: string; unit: string; article_type: string; product: string; months: (number | null)[] };
type Payload = { year: number; months: string[]; articles: Row[]; change_reasons: Option[] };

const TYPE_LABELS: Record<string, string> = { semi_fini: "semi-fini", fini: "produit fini" };

export default function Cibles() {
  const { me } = useSession();
  const [year, setYear] = useState<number>(new Date().getFullYear());
  const [data, setData] = useState<Payload | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Payload>(`dashboard/targets/?year=${year}`).then(setData).catch((e) => setError(errorText(e)));
  }, [year]);
  useEffect(() => {
    if (me) load();
  }, [me, load]);

  async function onSave(event: FormEvent<HTMLFormElement>, row: Row) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    const form = new FormData(event.currentTarget);
    const months = Array.from({ length: 12 }, (_, i) => {
      const v = String(form.get(`m${i}`) || "").trim().replace(/\s/g, "").replace(",", ".");
      return v === "" ? null : v;
    });
    try {
      const saved = await api<Row>("dashboard/targets/", { method: "PUT", body: JSON.stringify({ article: row.id, year, months, reason_code: form.get("reason_code") || "", reason_comment: form.get("reason_comment") || "" }) });
      setData((d) => (d ? { ...d, articles: d.articles.map((a) => (a.id === saved.id ? saved : a)) } : d));
      setMessage(`Cibles ${year} de « ${row.name} » enregistrées.`);
    } catch (e) {
      setError(errorText(e));
    }
  }

  if (!me) return null;
  const isAdmin = me.role === "admin";
  // Les produits qui ont une cible cette annee d'abord, les autres repliés (on en ajoute une en les ouvrant).
  const withTarget = (data?.articles || []).filter((r) => r.months.some((v) => v !== null));
  const without = (data?.articles || []).filter((r) => r.months.every((v) => v === null));
  const grid = (row: Row) => (
    <form key={`${row.id}-${year}`} onSubmit={(e) => onSave(e, row)} className="target-grid" style={{ margin: "0 0 18px" }}>
      <p style={{ margin: "0 0 6px" }}>
        <strong>{row.name}</strong>{" "}
        <small className="muted">
          ({row.code}, {TYPE_LABELS[row.article_type] || row.article_type}, produit « {row.product} », en {unitLabel(row.unit, 2)})
        </small>
      </p>
      <div className="table-wrap">
        <table className="detail-table">
          <thead>
            <tr>
              {data!.months.map((m) => (
                <th key={m} className="num">
                  {m}
                </th>
              ))}
              {isAdmin && <th />}
            </tr>
          </thead>
          <tbody>
            <tr>
              {row.months.map((v, i) => (
                <td key={i} className="num">
                  {isAdmin ? (
                    <input name={`m${i}`} inputMode="decimal" defaultValue={v === null ? "" : String(v).replace(".", ",")} aria-label={`${row.name}, ${data!.months[i]}`} />
                  ) : v === null ? (
                    "Aucune"
                  ) : (
                    v.toLocaleString("fr-FR")
                  )}
                </td>
              ))}
              {isAdmin && (
                <td>
                  <button type="submit">Enregistrer</button>
                </td>
              )}
            </tr>
          </tbody>
        </table>
      </div>
      {isAdmin && row.months.some((v) => v !== null) && (
        <p style={{ margin: "8px 0 0", display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <span className="muted">Si vous changez ou retirez une cible déjà saisie :</span>
          <CodePicker options={data!.change_reasons} label="Motif" name="reason_code" commentName="reason_comment" required={false} />
        </p>
      )}
    </form>
  );
  return (
    <main>
      <p>
        <Link href="/dashboard">Retour au tableau de bord</Link>
      </p>
      <h1>Cibles de production</h1>
      <p style={{ maxWidth: 820 }}>
        Une cible par produit et par mois, dans l&apos;unité de l&apos;article. Le tableau de bord compare la cible au réel déclaré
        (étapes de production, hors annulations). Pour un jour ou une semaine, la cible du mois est répartie sur ses jours.
        Case vide : pas de cible ce mois-là (hors saison par exemple).
        {!isAdmin && " Seul l'administrateur modifie les cibles."}
      </p>
      <label style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
        Année
        <select value={year} onChange={(e) => setYear(Number(e.target.value))}>
          {[-1, 0, 1].map((k) => {
            const y = new Date().getFullYear() + k;
            return (
              <option key={y} value={y}>
                {y}
              </option>
            );
          })}
        </select>
      </label>
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      {!data && !error && <p>Chargement...</p>}
      {data && (
        <section className="detail-block">
          <h3 className="detail-answer">{withTarget.length ? `${withTarget.length} produit(s) avec une cible en ${year}` : `Aucune cible en ${year}`}</h3>
          {withTarget.map(grid)}
          {without.length > 0 && (
            <details open={!withTarget.length}>
              <summary>Autres produits, sans cible en {year} ({without.length})</summary>
              <div style={{ marginTop: 12 }}>{without.map(grid)}</div>
            </details>
          )}
        </section>
      )}
    </main>
  );
}
