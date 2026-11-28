"use client";

// Controle qualite d'un lot (vrac seche, cartons) avant expedition. Chaque critere se coche conforme ou
// non conforme : pas de texte libre. Un critere non conforme bloque le lot automatiquement.
import { FormEvent, useCallback, useEffect, useState } from "react";
import { LateEntry, Option, OrganicBadge, errorText, lateFields, when, withUnit } from "@/components/Codes";
import { api } from "@/lib/api";

type Lot = {
  id: string;
  code: string;
  article_code: string;
  article_name: string;
  article_type: string;
  base_unit: string;
  organic_status: string;
  status: string;
  balance: string;
  block_reason: string;
  quality_checks?: { id: string; result: string; checked_at: string; moisture_pct: string | null; checks: Record<string, string>; username: string | null }[];
};
type Options = { criteria: Option[]; late_reasons: Option[] };
const big = { fontSize: "1.05em", padding: "8px 12px", minHeight: 40 };

export default function Qualite() {
  const [options, setOptions] = useState<Options | null>(null);
  const [lots, setLots] = useState<Lot[]>([]);
  const [lotId, setLotId] = useState("");
  const [checks, setChecks] = useState<Record<string, "ok" | "nok">>({});
  const [lot, setLot] = useState<Lot | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formKey, setFormKey] = useState(0);

  const load = useCallback(() => {
    api<Lot[]>("lots/?status=disponible")
      .then((all) => setLots(all.filter((l) => ["semi_fini", "fini"].includes(l.article_type) && Number(l.balance) > 0)))
      .catch((e) => setError(errorText(e)));
  }, []);
  useEffect(() => {
    api<Options>("lots/quality-checks/options/").then(setOptions).catch((e) => setError(errorText(e)));
    load();
  }, [load]);
  useEffect(() => {
    setLot(null);
    if (lotId) api<Lot>(`lots/${lotId}/`).then(setLot).catch(() => setLot(null));
  }, [lotId]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!Object.keys(checks).length) return setError("Cochez au moins un critère.");
    const form = new FormData(event.currentTarget);
    const moisture = String(form.get("moisture_pct") || "").trim().replace(",", ".");
    const late = lateFields(form);
    const payload: Record<string, unknown> = { checks, moisture_pct: moisture || null, ...late };
    if (late.occurred_at) {
      payload.checked_at = late.occurred_at;
      delete payload.occurred_at;
    }
    try {
      const result = await api<Lot>(`lots/${lotId}/quality-checks/`, { method: "POST", body: JSON.stringify(payload) });
      const blocked = result.status === "bloque";
      setMessage(
        blocked
          ? `Lot ${result.code} NON CONFORME : il est bloqué (${result.block_reason}). Voir Validations pour la suite.`
          : `Lot ${result.code} conforme : contrôle enregistré.`,
      );
      setChecks({});
      setLotId("");
      setFormKey((k) => k + 1);
      load();
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <main>
      <h1>Contrôle qualité</h1>
      <p>Contrôlez le vrac séché ou les cartons avant l&apos;expédition. Un seul critère non conforme bloque le lot.</p>
      {message && <p style={{ background: "#e8f5e9", padding: 8, fontSize: "1.1em" }}>{message}</p>}
      {error && <p role="alert">{error}</p>}
      {options && (
        <form key={formKey} onSubmit={onSubmit} style={{ display: "grid", gap: 12, maxWidth: 820, border: "1px solid #888", padding: 12 }}>
          <label>
            Lot contrôlé{" "}
            <select required value={lotId} onChange={(e) => setLotId(e.target.value)} style={big}>
              <option value="">(choisir)</option>
              {lots.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.code} · {l.article_name} · {withUnit(l.balance, l.base_unit)}
                </option>
              ))}
            </select>
          </label>
          {lot && (
            <p style={{ margin: 0 }}>
              <OrganicBadge status={lot.organic_status} />{" "}
              {lot.quality_checks && lot.quality_checks.length > 0
                ? `Dernier contrôle : ${lot.quality_checks[0].result === "conforme" ? "conforme" : "non conforme"} le ${when(lot.quality_checks[0].checked_at)}.`
                : "Aucun contrôle sur ce lot."}
            </p>
          )}
          <table cellPadding={4}>
            <tbody>
              {options.criteria.map((c) => (
                <tr key={c.code}>
                  <td>{c.label}</td>
                  <td>
                    {(["ok", "nok"] as const).map((v) => (
                      <button
                        type="button"
                        key={v}
                        onClick={() => setChecks((old) => ({ ...old, [c.code]: v }))}
                        style={{
                          ...big,
                          marginRight: 6,
                          background: checks[c.code] === v ? (v === "ok" ? "#1b5e20" : "#b00020") : undefined,
                          color: checks[c.code] === v ? "white" : undefined,
                        }}
                      >
                        {v === "ok" ? "Conforme" : "Non conforme"}
                      </button>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <label>
            Humidité mesurée <input name="moisture_pct" inputMode="decimal" style={{ ...big, width: 80 }} /> %{" "}
            <small style={{ color: "#555" }}>(facultatif, à reporter du testeur)</small>
          </label>
          <LateEntry reasons={options.late_reasons} label="Date et heure du contrôle" />
          <div>
            <button type="submit" style={{ ...big, fontWeight: "bold" }}>
              Enregistrer le contrôle
            </button>
          </div>
        </form>
      )}
    </main>
  );
}
