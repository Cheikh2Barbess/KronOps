"use client";

// Arrets de ligne : un equipement s'arrete, l'operateur le declare au poste en trois choix (equipement, cause,
// en cours ou termine). Les causes sont une liste fermee, classee planifiee ou non. « Autre » demande une precision.
// Un arret en cours se termine d'un clic. Une erreur s'annule avec un motif (Admin, Production) : rien n'est efface.
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useCallback, useEffect, useState } from "react";
import { useSession } from "@/components/AppShell";
import { CodePicker, Option, errorText, when } from "@/components/Codes";
import { Icon } from "@/components/Icon";
import { StatusBadge } from "@/components/Status";
import { api } from "@/lib/api";

type Cause = Option & { planned: boolean };
type Equipment = { id: string; code: string; name: string; site_name: string | null };
type Options = { causes: Cause[]; cancel_reasons: Option[]; equipment: Equipment[] };
type Stop = {
  id: string;
  equipment_code: string;
  equipment_name: string;
  site_name: string | null;
  started_at: string;
  ended_at: string | null;
  ongoing: boolean;
  duration_hours: number;
  cause_code: string;
  cause_label: string;
  planned: boolean;
  username: string | null;
  ended_by: string | null;
  cancelled: { at: string; by: string | null; reason: string } | null;
};

const big = { fontSize: "1.05em", padding: "10px 14px", minHeight: 44 };
const hours = (h: number) => `${h.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} h`;
const toIso = (v: FormDataEntryValue | null) => (v ? new Date(String(v)).toISOString() : null);

export default function ArretsPage() {
  return (
    <Suspense fallback={<p>Chargement...</p>}>
      <Arrets />
    </Suspense>
  );
}

// Filtres venus d'un clic au tableau de bord (Pareto, frise) : ?cause=...&equipment=...&days=...
function Arrets() {
  const { me } = useSession();
  const params = useSearchParams();
  const cause = params.get("cause") || "";
  const equipmentFilter = params.get("equipment") || "";
  const [options, setOptions] = useState<Options | null>(null);
  const [rows, setRows] = useState<Stop[]>([]);
  const [days, setDays] = useState(() => {
    const d = Number(params.get("days"));
    return [7, 30, 90, 365].includes(d) ? d : 30;
  });
  const [mode, setMode] = useState<"now" | "past">("now");
  const [cancelling, setCancelling] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formKey, setFormKey] = useState(0);

  const load = useCallback(() => {
    api<Options>("production/stops/options/").then(setOptions).catch((e) => setError(errorText(e)));
    const query = new URLSearchParams({ days: String(days) });
    if (cause) query.set("cause", cause);
    if (equipmentFilter) query.set("equipment", equipmentFilter);
    api<Stop[]>(`production/stops/?${query.toString()}`).then(setRows).catch((e) => setError(errorText(e)));
  }, [days, cause, equipmentFilter]);
  useEffect(() => {
    if (me) load();
  }, [me, load]);

  if (!me) return null;
  const canDeclare = ["admin", "production", "operateur"].includes(me.role);
  const canCancel = ["admin", "production"].includes(me.role);
  const canCall = ["admin", "production", "qualite", "operateur"].includes(me.role);
  const ongoing = rows.filter((r) => r.ongoing);
  const filtered = Boolean(cause || equipmentFilter);
  const causeLabel = options?.causes.find((c) => c.code === cause)?.label || cause;
  const equipmentLabel = options?.equipment.find((e) => e.id === equipmentFilter)?.code || "un équipement";

  async function onDeclare(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    const form = new FormData(event.currentTarget);
    const payload: Record<string, unknown> = {
      equipment: form.get("equipment"),
      cause_code: form.get("cause_code"),
      comment: form.get("comment") || "",
    };
    if (mode === "past") {
      payload.started_at = toIso(form.get("started_at"));
      payload.ended_at = toIso(form.get("ended_at"));
    }
    try {
      const stop = await api<Stop>("production/stops/", { method: "POST", body: JSON.stringify(payload) });
      setMessage(stop.ongoing ? `Arrêt de ${stop.equipment_code} déclaré en cours. Terminez-le quand la ligne repart.` : `Arrêt de ${stop.equipment_code} enregistré (${hours(stop.duration_hours)}).`);
      setFormKey((k) => k + 1);
      load();
    } catch (e) {
      setError(errorText(e));
    }
  }

  async function onEnd(stop: Stop) {
    setError(null);
    try {
      const done = await api<Stop>(`production/stops/${stop.id}/end/`, { method: "POST", body: "{}" });
      setMessage(`${done.equipment_code} repart : arrêt de ${hours(done.duration_hours)} terminé.`);
      load();
    } catch (e) {
      setError(errorText(e));
    }
  }

  // Appel au poste : la maintenance ou la qualite est prevenue par une action a attribuer, priorite haute.
  async function onCall(stop: Stop, actionType: "maintenance" | "qualite") {
    setError(null);
    try {
      await api("actions/call/", { method: "POST", body: JSON.stringify({ line_stop: stop.id, action_type: actionType }) });
      setMessage(`${actionType === "maintenance" ? "Maintenance" : "Qualité"} appelée pour ${stop.equipment_code}. L'appel est dans l'écran Actions, à attribuer.`);
    } catch (e) {
      setError(errorText(e));
    }
  }

  async function onCancel(event: FormEvent<HTMLFormElement>, stop: Stop) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    try {
      await api<Stop>(`production/stops/${stop.id}/cancel/`, {
        method: "POST",
        body: JSON.stringify({ reason_code: form.get("reason_code"), comment: form.get("comment") || "" }),
      });
      setMessage(`Arrêt de ${stop.equipment_code} annulé (il reste visible, barré, au journal).`);
      setCancelling(null);
      load();
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <main>
      <h1>Arrêts de ligne</h1>
      <p style={{ maxWidth: 820 }}>
        Un séchoir ou une ligne s&apos;arrête : déclarez-le ici. Les arrêts planifiés (nettoyage, maintenance préventive) sont
        comptés à part des arrêts subis (panne, coupure, manque). Le tableau de bord les additionne par cause et par équipement.
      </p>
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}
      {error && <p role="alert">{error}</p>}

      {ongoing.length > 0 && (
        <section className="detail-block">
          <h3 className="detail-answer">
            {ongoing.length} arrêt{ongoing.length > 1 ? "s" : ""} en cours
          </h3>
          <div style={{ display: "grid", gap: 10 }}>
            {ongoing.map((s) => (
              <div key={s.id} className="stop-card">
                <span style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                  <StatusBadge status="warn" text="En cours" />
                  <strong>
                    {s.equipment_code} {s.equipment_name}
                  </strong>
                  <span className="muted">{s.site_name || "Sans site"}</span>
                </span>
                <span>
                  {s.cause_label}, depuis le {when(s.started_at)} ({hours(s.duration_hours)})
                </span>
                <span style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                  {canDeclare && (
                    <button type="button" onClick={() => onEnd(s)} style={big}>
                      <Icon name="check" size={16} />
                      La ligne repart : terminer l&apos;arrêt
                    </button>
                  )}
                  {canCall && (
                    <>
                      <button type="button" onClick={() => onCall(s, "maintenance")} style={big}>
                        <Icon name="wrench" size={16} />
                        Appeler la maintenance
                      </button>
                      <button type="button" onClick={() => onCall(s, "qualite")} style={big}>
                        <Icon name="clipboard-check" size={16} />
                        Appeler la qualité
                      </button>
                    </>
                  )}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {canDeclare && options && (
        <form key={formKey} onSubmit={onDeclare} className="detail-block" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 12, maxWidth: 860 }}>
          <h3 className="detail-answer">Déclarer un arrêt</h3>
          <label>
            <strong>1. Équipement</strong>{" "}
            <select name="equipment" required defaultValue="" style={{ ...big, width: "100%", maxWidth: 560 }}>
              <option value="" disabled>
                (choisir)
              </option>
              {options.equipment.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.site_name || "Sans site"} · {e.code} · {e.name}
                </option>
              ))}
            </select>
          </label>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center" }}>
            <strong>2. Cause</strong>
            <CodePicker
              options={options.causes.map((c) => ({ code: c.code, label: c.label }))}
              label=""
              name="cause_code"
              commentName="comment"
            />
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center" }}>
            <strong>3. Quand</strong>
            <label>
              <input type="radio" checked={mode === "now"} onChange={() => setMode("now")} /> Arrêtée maintenant (en cours)
            </label>
            <label>
              <input type="radio" checked={mode === "past"} onChange={() => setMode("past")} /> Arrêt déjà terminé
            </label>
          </div>
          {mode === "past" && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
              <label>
                Début <input type="datetime-local" name="started_at" required />
              </label>
              <label>
                Fin <input type="datetime-local" name="ended_at" required />
              </label>
            </div>
          )}
          <div>
            <button type="submit" style={big}>
              <Icon name="circle-pause" size={16} />
              Déclarer l&apos;arrêt
            </button>
          </div>
        </form>
      )}

      <section className="detail-block">
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "center", marginBottom: 10 }}>
          <h3 className="detail-answer" style={{ margin: 0 }}>
            {filtered ? "Arrêts filtrés" : "Arrêts récents"}
          </h3>
          {filtered && (
            <span style={{ display: "inline-flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              {cause && <span className="status-badge">Cause : {causeLabel}</span>}
              {equipmentFilter && <span className="status-badge">Équipement : {equipmentLabel}</span>}
              <Link href="/arrets">Tout afficher</Link>
            </span>
          )}
          <label style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
            <span className="muted">Depuis</span>
            <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
              <option value={7}>7 jours</option>
              <option value={30}>30 jours</option>
              <option value={90}>3 mois</option>
              <option value={365}>12 mois</option>
            </select>
          </label>
        </div>
        {rows.length === 0 ? (
          <p className="muted">Aucun arrêt déclaré sur la période.</p>
        ) : (
          <div className="table-wrap">
            <table className="detail-table">
              <thead>
                <tr>
                  <th>Début</th>
                  <th>Fin</th>
                  <th className="num">Durée</th>
                  <th>Équipement</th>
                  <th>Cause</th>
                  <th>Type</th>
                  <th>Déclaré par</th>
                  {canCancel && <th />}
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.id} style={s.cancelled ? { textDecoration: "line-through", color: "var(--muted)" } : undefined}>
                    <td>{when(s.started_at)}</td>
                    <td>{s.ongoing ? <StatusBadge status="warn" text="En cours" /> : s.ended_at ? when(s.ended_at) : "Annulé"}</td>
                    <td className="num">{hours(s.duration_hours)}</td>
                    <td>
                      {s.equipment_code}
                      <br />
                      <small>{s.equipment_name}</small>
                    </td>
                    <td>
                      {s.cause_label}
                      {s.cancelled && (
                        <>
                          <br />
                          <small>Annulé : {s.cancelled.reason}</small>
                        </>
                      )}
                    </td>
                    <td>{s.planned ? "Planifié" : "Non planifié"}</td>
                    <td>{s.username || "Inconnu"}</td>
                    {canCancel && (
                      <td>
                        {!s.cancelled &&
                          (cancelling === s.id && options ? (
                            <form onSubmit={(e) => onCancel(e, s)} style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
                              <CodePicker options={options.cancel_reasons} label="Motif" name="reason_code" commentName="comment" />
                              <button type="submit">Annuler l&apos;arrêt</button>
                              <button type="button" onClick={() => setCancelling(null)}>
                                Garder
                              </button>
                            </form>
                          ) : (
                            <button type="button" onClick={() => setCancelling(s.id)}>
                              Annuler…
                            </button>
                          ))}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
