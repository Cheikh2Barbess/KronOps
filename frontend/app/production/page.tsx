"use client";

// Declarer une etape de production, au poste, sur tablette : gros boutons, listes, aucune saisie libre
// hors quantites. Un lot peut etre consomme en partie (le reste reste en stock) et reparti sur plusieurs
// sechoirs (une declaration par sechoir). Les regles (melange bio, rendement, saisie tardive) sont
// appliquees par l'API, l'ecran les annonce avant l'envoi.
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  CodePicker,
  LateEntry,
  LateFlag,
  Menu,
  ORGANIC,
  Option,
  OrganicBadge,
  errorText,
  fmt,
  lateFields,
  when,
  withUnit,
} from "@/components/Codes";
import { Run, YieldCell } from "@/components/Runs";
import { api } from "@/lib/api";

type Me = { username: string; role: string };
type Lot = {
  id: string;
  code: string;
  article_code: string;
  article_name: string;
  article_type: string;
  base_unit: string;
  organic_status: string;
  parcel_code: string | null;
  site: string | null;
  site_name: string | null;
  balance: string;
};
type Conversion = { unit_name: string; factor: string };
type OutArticle = {
  id: string;
  code: string;
  name: string;
  article_type: string;
  base_unit: string;
  yield_min_pct: string | null;
  yield_max_pct: string | null;
  conversions: Conversion[];
};
type Equipment = { id: string; code: string; name: string; equipment_type: string; site: string | null; site_name: string | null };
type Options = {
  steps: Option[];
  equipment: Equipment[];
  sites: { id: string; name: string }[];
  lots: Lot[];
  output_articles: OutArticle[];
  waste_reasons: Option[];
  late_reasons: Option[];
  cancel_reasons: Option[];
};
const STEP_EQUIPMENT: Record<string, string[]> = {
  murissement: ["murissement"],
  tri: ["tri"],
  preparation: ["preparation"],
  sechage: ["sechoir"],
  conditionnement: ["conditionnement"],
  palettisation: ["conditionnement"],
};
const big = { fontSize: "1.1em", padding: "10px 14px", minHeight: 44 };

type InputRow = { lot: string; quantity: string };

function DeclareForm({ options, onDone }: { options: Options; onDone: (run: Run) => void }) {
  const [step, setStep] = useState("");
  const [equipmentId, setEquipmentId] = useState("");
  const [rows, setRows] = useState<InputRow[]>([{ lot: "", quantity: "" }]);
  const [articleId, setArticleId] = useState("");
  const [outQty, setOutQty] = useState("");
  const [outUnit, setOutUnit] = useState("");
  const [waste, setWaste] = useState("");
  const [siteId, setSiteId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const lotById = useMemo(() => Object.fromEntries(options.lots.map((l) => [l.id, l])), [options.lots]);
  const article = options.output_articles.find((a) => a.id === articleId);
  const equipment = options.equipment.filter((e) => !step || (STEP_EQUIPMENT[step] || []).includes(e.equipment_type) || e.equipment_type === "autre");
  const chosen = rows.map((r) => lotById[r.lot]).filter(Boolean) as Lot[];
  const food = chosen.filter((l) => l.article_type !== "emballage");
  const statuses = new Set(food.map((l) => l.organic_status));
  const num = (v: string) => Number((v || "").replace(",", "."));
  const factor = article && outUnit && outUnit !== article.base_unit ? num(article.conversions.find((c) => c.unit_name === outUnit)?.factor || "0") : 1;
  const outBase = num(outQty) * factor;
  const massIn = rows.reduce((sum, r) => {
    const l = lotById[r.lot];
    return l && article && l.article_type !== "emballage" && l.base_unit === article.base_unit ? sum + num(r.quantity) : sum;
  }, 0);
  const pct = massIn > 0 && outBase > 0 ? (outBase * 100) / massIn : null;
  const min = article?.yield_min_pct ? Number(article.yield_min_pct) : null;
  const max = article?.yield_max_pct ? Number(article.yield_max_pct) : null;
  const outOfRange = pct !== null && min !== null && max !== null && (pct < min || pct > max);

  function setRow(i: number, patch: Partial<InputRow>) {
    setRows((old) => old.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    const payload: Record<string, unknown> = {
      step,
      equipment: equipmentId || null,
      inputs: rows.filter((r) => r.lot).map((r) => ({ lot: r.lot, quantity: String(num(r.quantity)) })),
      output_article: articleId,
      output_quantity: String(num(outQty)),
      output_unit: outUnit,
      ...lateFields(form),
    };
    if (siteId) payload.site = siteId;
    if (num(waste) > 0) {
      payload.waste_quantity = String(num(waste));
      payload.waste_code = form.get("waste_code");
      payload.waste_comment = form.get("waste_comment") || "";
    }
    if (payload.occurred_at) {
      payload.ended_at = payload.occurred_at;
      delete payload.occurred_at;
    }
    setSending(true);
    try {
      onDone(await api<Run>("production/runs/", { method: "POST", body: JSON.stringify(payload) }));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setSending(false);
    }
  }

  const equipmentSite = options.equipment.find((e) => e.id === equipmentId)?.site || null;
  const needsSite = options.sites.length > 1 && !equipmentSite;
  // Un lot se consomme dans l'usine ou il se trouve : les autres sont caches (transfert d'abord).
  const workSite = equipmentSite || siteId || null;
  const lotsHere = options.lots.filter((l) => !workSite || !l.site || l.site === workSite);
  const hiddenElsewhere = options.lots.length - lotsHere.length;
  return (
    <form onSubmit={onSubmit} style={{ display: "grid", gap: 14, maxWidth: 860, border: "1px solid #888", padding: 12 }}>
      <div>
        <strong>1. Étape</strong>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 6 }}>
          {options.steps.map((s) => (
            <button
              type="button"
              key={s.code}
              onClick={() => {
                setStep(s.code);
                setEquipmentId("");
              }}
              style={{ ...big, background: step === s.code ? "#1b5e20" : undefined, color: step === s.code ? "white" : undefined }}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>
      {step && (
        <>
          <label>
            <strong>2. Équipement</strong>{" "}
            <select value={equipmentId} onChange={(e) => setEquipmentId(e.target.value)} style={big}>
              <option value="">(aucun)</option>
              {equipment.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.code} {e.name}
                  {e.site_name ? ` · ${e.site_name}` : ""}
                </option>
              ))}
            </select>
          </label>
          {needsSite && (
            <label>
              Site{" "}
              <select name="site" required value={siteId} onChange={(e) => setSiteId(e.target.value)} style={big}>
                <option value="" disabled>
                  (choisir)
                </option>
                {options.sites.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div>
            <strong>3. Lots consommés</strong>{" "}
            <small style={{ color: "#555" }}>(une partie du lot suffit : le reste reste en stock)</small>
            {rows.map((r, i) => {
              const lot = lotById[r.lot];
              return (
                <div key={i} style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", marginTop: 6 }}>
                  <select value={r.lot} onChange={(e) => setRow(i, { lot: e.target.value, quantity: "" })} style={{ ...big, maxWidth: 480 }}>
                    <option value="">(choisir un lot)</option>
                    {lotsHere.map((l) => (
                      <option key={l.id} value={l.id} disabled={rows.some((x, j) => j !== i && x.lot === l.id)}>
                        {l.code} · {l.article_name} · {withUnit(l.balance, l.base_unit)}
                        {l.organic_status ? ` · ${ORGANIC[l.organic_status]}` : ""}
                        {l.parcel_code ? ` · ${l.parcel_code}` : ""}
                        {options.sites.length > 1 && l.site_name ? ` · ${l.site_name}` : ""}
                      </option>
                    ))}
                  </select>
                  {lot && (
                    <>
                      <input
                        aria-label="Quantité consommée"
                        value={r.quantity}
                        onChange={(e) => setRow(i, { quantity: e.target.value })}
                        inputMode="decimal"
                        required
                        style={{ ...big, width: 110 }}
                      />{" "}
                      {withUnit(2, lot.base_unit).replace(/^2 /, "")}
                      <button type="button" onClick={() => setRow(i, { quantity: lot.balance })} style={big}>
                        Tout le lot
                      </button>
                      <OrganicBadge status={lot.organic_status} />
                    </>
                  )}
                  {rows.length > 1 && (
                    <button type="button" onClick={() => setRows((old) => old.filter((_, j) => j !== i))} aria-label="Retirer ce lot">
                      ✕
                    </button>
                  )}
                </div>
              );
            })}
            <button type="button" onClick={() => setRows((old) => [...old, { lot: "", quantity: "" }])} style={{ ...big, marginTop: 6 }}>
              + Ajouter un lot
            </button>
            {hiddenElsewhere > 0 && (
              <p style={{ color: "#555", margin: "6px 0 0" }}>
                {hiddenElsewhere} lot(s) d&apos;une autre usine ne sont pas proposés. Pour les utiliser ici, faites d&apos;abord un{" "}
                <a href="/transferts">transfert</a>.
              </p>
            )}
            {statuses.size > 1 && (
              <p role="alert" style={{ color: "#b00020" }}>
                Mélange interdit : ces lots n&apos;ont pas le même statut bio ({[...statuses].map((s) => ORGANIC[s] || "non renseigné").join(", ")}).
              </p>
            )}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
            <strong>4. Produit obtenu</strong>
            <select
              required
              value={articleId}
              onChange={(e) => {
                setArticleId(e.target.value);
                setOutUnit(options.output_articles.find((a) => a.id === e.target.value)?.base_unit || "");
              }}
              style={big}
            >
              <option value="">(choisir)</option>
              {options.output_articles.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.code} {a.name}
                </option>
              ))}
            </select>
            {article && (
              <>
                <input aria-label="Quantité produite" value={outQty} onChange={(e) => setOutQty(e.target.value)} required inputMode="decimal" style={{ ...big, width: 110 }} />
                <select aria-label="Unité" value={outUnit} onChange={(e) => setOutUnit(e.target.value)} style={big}>
                  <option value={article.base_unit}>{withUnit(2, article.base_unit).replace(/^2 /, "")}</option>
                  {article.conversions.map((c) => (
                    <option key={c.unit_name} value={c.unit_name}>
                      {c.unit_name} ({withUnit(c.factor, article.base_unit)})
                    </option>
                  ))}
                </select>
                {factor !== 1 && outBase > 0 && <span>soit {withUnit(outBase, article.base_unit)}</span>}
              </>
            )}
          </div>
          {article && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
              <strong>5. Déchets écartés</strong>
              <input aria-label="Déchets" value={waste} onChange={(e) => setWaste(e.target.value)} inputMode="decimal" placeholder="0" style={{ ...big, width: 90 }} />{" "}
              {withUnit(2, article.base_unit).replace(/^2 /, "")}
              {num(waste) > 0 && <CodePicker options={options.waste_reasons} label="Nature" name="waste_code" commentName="waste_comment" />}
            </div>
          )}
          {pct !== null && article && (
            <p style={{ fontSize: "1.1em", color: outOfRange ? "#b00020" : "#1b5e20", margin: 0 }}>
              Rendement : <strong>{fmt(pct.toFixed(2))} %</strong>
              {pct < 50 ? ` (${fmt((100 / pct).toFixed(1))} kg pour 1 kg)` : ""}
              {min !== null && max !== null
                ? outOfRange
                  ? ` · hors fourchette attendue ${fmt(min)} à ${fmt(max)} % : l'écart sera signalé au bilan matière.`
                  : ` · dans la fourchette attendue ${fmt(min)} à ${fmt(max)} %.`
                : " · pas de rendement de référence pour cet article."}
            </p>
          )}
          <LateEntry reasons={options.late_reasons} label="Fin réelle de l'étape" />
          <div>
            <button type="submit" disabled={sending || statuses.size > 1} style={{ ...big, fontWeight: "bold" }}>
              {sending ? "Enregistrement..." : "Enregistrer l'étape"}
            </button>
          </div>
        </>
      )}
      {error && (
        <p role="alert" style={{ color: "#b00020" }}>
          {error}
        </p>
      )}
    </form>
  );
}

function CancelRun({ run, reasons, onDone }: { run: Run; reasons: Option[]; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!open)
    return (
      <button type="button" onClick={() => setOpen(true)}>
        Annuler l&apos;étape
      </button>
    );
  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError(null);
    try {
      await api(`production/runs/${run.id}/cancel/`, {
        method: "POST",
        body: JSON.stringify({ reason_code: form.get("reason_code"), comment: form.get("comment") || "" }),
      });
      onDone();
    } catch (e) {
      setError(errorText(e));
    }
  }
  return (
    <form onSubmit={onSubmit} style={{ display: "grid", gap: 6, border: "1px solid #b00020", padding: 6 }}>
      <small>
        Les quantités consommées reviennent en stock, le lot {run.output_lot_code} est bloqué. L&apos;étape reste visible, marquée
        annulée.
      </small>
      <CodePicker options={reasons} label="Motif" name="reason_code" commentName="comment" />
      <span>
        <button type="submit">Confirmer l&apos;annulation</button>{" "}
        <button type="button" onClick={() => setOpen(false)}>
          Garder
        </button>
      </span>
      {error && (
        <span role="alert" style={{ color: "#b00020" }}>
          {error}
        </span>
      )}
    </form>
  );
}

export default function Production() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [options, setOptions] = useState<Options | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formKey, setFormKey] = useState(0);

  const load = useCallback(() => {
    api<Options>("production/runs/options/").then(setOptions).catch((e) => setError(errorText(e)));
    api<Run[]>("production/runs/").then(setRuns).catch(() => setRuns([]));
  }, []);
  useEffect(() => {
    api<Me>("auth/me/").then(setMe).catch(() => setMe(null));
  }, []);
  useEffect(() => {
    if (me) load();
  }, [me, load]);

  if (me === undefined) return <main><p>Chargement...</p></main>;
  if (me === null)
    return (
      <main>
        <p role="alert">Connectez-vous d&apos;abord.</p>
        <a href="/">Accueil</a>
      </main>
    );
  const canDeclare = ["admin", "production", "operateur"].includes(me.role);
  const canCancel = ["admin", "production"].includes(me.role);

  return (
    <main>
      <Menu />
      <h1>Production : déclarer une étape</h1>
      <p>
        Déclarez chaque étape au moment où elle se termine : l&apos;heure est prise automatiquement. Tracalys crée le lot produit,
        retire les quantités consommées et calcule le rendement.
      </p>
      {message && <p style={{ background: "#e8f5e9", padding: 8, fontSize: "1.1em" }}>{message}</p>}
      {error && <p role="alert">{error}</p>}
      {canDeclare && options && (
        <DeclareForm
          key={formKey}
          options={options}
          onDone={(run) => {
            setMessage(
              `Lot ${run.output_lot_code} créé : ${withUnit(run.output_quantity, run.base_unit)} de ${run.output_article_name}` +
                (run.organic_status ? ` (${ORGANIC[run.organic_status]})` : "") +
                ". Écrivez ce numéro sur l'étiquette.",
            );
            setFormKey((k) => k + 1);
            load();
          }}
        />
      )}
      <h2>Dernières étapes</h2>
      {runs.length === 0 ? (
        <p>Aucune étape déclarée.</p>
      ) : (
        <table cellPadding={4} style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr style={{ textAlign: "left" }}>
              <th>Fin</th>
              <th>Étape</th>
              <th>Lots consommés</th>
              <th>Lot produit</th>
              <th>Rendement</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id} style={{ borderTop: "1px solid #ddd", verticalAlign: "top", opacity: r.cancelled ? 0.6 : 1 }}>
                <td>
                  {when(r.ended_at)}
                  <br />
                  <LateFlag late={r.late} />
                </td>
                <td>
                  {r.step_label}
                  {r.equipment_code && (
                    <>
                      <br />
                      <small>
                        {r.equipment_code} {r.equipment_name}
                      </small>
                    </>
                  )}
                </td>
                <td>
                  {r.inputs.map((i) => (
                    <div key={i.lot_code}>
                      {i.lot_code} : {withUnit(i.quantity, i.base_unit)}
                    </div>
                  ))}
                </td>
                <td>
                  <strong>{r.output_lot_code}</strong> <OrganicBadge status={r.organic_status} />
                  <br />
                  {withUnit(r.output_quantity, r.base_unit)} {r.output_article_name}
                </td>
                <td>
                  <YieldCell run={r} />
                  {canCancel && options && r.cancellable && (
                    <div style={{ marginTop: 6 }}>
                      <CancelRun
                        run={r}
                        reasons={options.cancel_reasons}
                        onDone={() => {
                          setMessage(`Étape annulée : le lot ${r.output_lot_code} est bloqué, les quantités consommées sont revenues en stock.`);
                          load();
                        }}
                      />
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
