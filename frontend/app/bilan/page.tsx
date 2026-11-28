"use client";

// Bilan matiere : chaque etape declaree avec sa matiere consommee, son produit, ses dechets et son rendement.
// Un rendement hors de la fourchette attendue de l'article est signale. Les saisies tardives aussi.
import { FormEvent, useCallback, useEffect, useState } from "react";
import { LateFlag, Option, OrganicBadge, errorText, fmt, when, withUnit } from "@/components/Codes";
import { Run, YieldCell } from "@/components/Runs";
import { api } from "@/lib/api";

type Total = {
  step: string;
  step_label: string;
  unit: string;
  runs: number;
  input_quantity: string;
  output_quantity: string;
  waste_quantity: string;
  yield_pct: string | null;
  deviations: number;
  late_entries: number;
};
type Balance = { runs: Run[]; totals: Total[]; steps: Option[]; sites: { id: string; name: string }[] };

export default function Bilan() {
  const [data, setData] = useState<Balance | null>(null);
  const [query, setQuery] = useState("");
  const [onlyIssues, setOnlyIssues] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Balance>(`production/balance/${query}`).then(setData).catch((e) => setError(errorText(e)));
  }, [query]);
  useEffect(load, [load]);

  function onFilter(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const params = new URLSearchParams();
    for (const key of ["date_from", "date_to", "step", "site"]) {
      const v = String(form.get(key) || "");
      if (v) params.set(key, v);
    }
    setQuery(params.toString() ? `?${params}` : "");
  }

  const runs = (data?.runs || []).filter((r) => !onlyIssues || r.late || r.yield_status === "bas" || r.yield_status === "haut");
  return (
    <main>
      <h1>Bilan matière</h1>
      <p>
        Pour chaque étape : matière consommée, produit obtenu, déchets déclarés et rendement. Le reste (eau évaporée au séchage,
        ou perte non expliquée) est calculé. Un rendement hors de la fourchette attendue est signalé en rouge.
      </p>
      {error && <p role="alert">{error}</p>}
      <form onSubmit={onFilter} className="no-print" style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
        <label>
          Du <input type="date" name="date_from" />
        </label>
        <label>
          au <input type="date" name="date_to" />
        </label>
        <select name="step" defaultValue="">
          <option value="">Toutes les étapes</option>
          {data?.steps.map((s) => (
            <option key={s.code} value={s.code}>
              {s.label}
            </option>
          ))}
        </select>
        {data && data.sites.length > 1 && (
          <select name="site" defaultValue="">
            <option value="">Tous les sites</option>
            {data.sites.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        )}
        <button type="submit">Afficher</button>
        <label>
          <input type="checkbox" checked={onlyIssues} onChange={(e) => setOnlyIssues(e.target.checked)} /> Seulement les écarts et
          saisies tardives
        </label>
        <button type="button" onClick={() => window.print()}>
          Imprimer
        </button>
      </form>
      {data && (
        <>
          <h2>Total par étape</h2>
          {data.totals.length === 0 ? (
            <p>Aucune étape sur la période.</p>
          ) : (
            <table cellPadding={4} style={{ width: "100%" }}>
              <thead>
                <tr style={{ textAlign: "left" }}>
                  <th>Étape</th>
                  <th className="num">Déclarations</th>
                  <th className="num">Consommé</th>
                  <th className="num">Produit</th>
                  <th className="num">Déchets</th>
                  <th className="num">Rendement</th>
                  <th className="num">Écarts</th>
                  <th className="num">Saisies tardives</th>
                </tr>
              </thead>
              <tbody>
                {data.totals.map((t) => (
                  <tr key={t.step}>
                    <td>{t.step_label}</td>
                    <td className="num">{t.runs}</td>
                    <td className="num">{withUnit(t.input_quantity, t.unit)}</td>
                    <td className="num">{withUnit(t.output_quantity, t.unit)}</td>
                    <td className="num">{withUnit(t.waste_quantity, t.unit)}</td>
                    <td className="num">{t.yield_pct === null ? "" : `${fmt(t.yield_pct)} %`}</td>
                    <td className="num" style={{ color: t.deviations ? "#b00020" : undefined }}>{t.deviations}</td>
                    <td className="num" style={{ color: t.late_entries ? "#8a5a00" : undefined }}>{t.late_entries}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <h2>Détail des étapes</h2>
          <table cellPadding={4} style={{ width: "100%" }}>
            <thead>
              <tr style={{ textAlign: "left" }}>
                <th>Fin</th>
                <th>Étape</th>
                <th className="num">Consommé</th>
                <th className="num">Produit</th>
                <th className="num">Déchets</th>
                <th className="num">Reste (eau, écart)</th>
                <th className="num">Rendement</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr
                  key={r.id}
                  style={{
                    verticalAlign: "top",
                    background: r.yield_status === "bas" || r.yield_status === "haut" ? "#fdecea" : undefined,
                  }}
                >
                  <td>
                    {when(r.ended_at)}
                    <br />
                    <LateFlag late={r.late} />
                    {r.late && r.late_reason_label && (
                      <>
                        <br />
                        <small>{r.late_reason_label}</small>
                      </>
                    )}
                  </td>
                  <td>
                    {r.step_label}
                    {r.equipment_code && (
                      <>
                        <br />
                        <small>{r.equipment_code}</small>
                      </>
                    )}
                    {r.site_name && (
                      <>
                        <br />
                        <small>{r.site_name}</small>
                      </>
                    )}
                  </td>
                  <td className="num">
                    {withUnit(r.input_quantity, r.base_unit)}
                    {r.inputs.map((i) => (
                      <div key={i.lot_code}>
                        <small>
                          {i.lot_code} {i.parcel_code ? `(${i.parcel_code})` : ""}
                        </small>
                      </div>
                    ))}
                  </td>
                  <td className="num">
                    {withUnit(r.output_quantity, r.base_unit)}
                    <br />
                    <small>
                      {r.output_lot_code} <OrganicBadge status={r.organic_status} />
                    </small>
                  </td>
                  <td className="num">
                    {Number(r.waste_quantity) ? withUnit(r.waste_quantity, r.base_unit) : ""}
                    {r.waste_label && (
                      <>
                        <br />
                        <small>{r.waste_label}</small>
                      </>
                    )}
                  </td>
                  <td className="num">{r.unexplained_quantity === null ? "" : withUnit(r.unexplained_quantity, r.base_unit)}</td>
                  <td className="num">
                    <YieldCell run={r} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {runs.length === 0 && <p>Rien à afficher.</p>}
        </>
      )}
    </main>
  );
}
