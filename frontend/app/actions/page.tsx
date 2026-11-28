"use client";

// Actions : qui fait quoi, pour quand. Une alerte (produit sous la cible, arret trop long, lot bloque, action en
// retard) propose de creer l'action, deja pre-remplie. Tout se choisit dans des listes, le texte libre ne sert qu'a
// preciser « Autre ». Une action avance par etapes (attribuer, commencer, terminer, annuler) : rien n'est efface.
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useCallback, useEffect, useState } from "react";
import { useSession } from "@/components/AppShell";
import { CodePicker, Option, day, errorText, when } from "@/components/Codes";
import { Icon } from "@/components/Icon";
import { Status, StatusBadge } from "@/components/Status";
import { api } from "@/lib/api";

type Person = { id: string; username: string; name: string; role: string };
type Subject = Option & { action_type: string | null };
type Options = { types: Option[]; subjects: Subject[]; priorities: Option[]; results: Option[]; cancel_reasons: Option[]; people: Person[] };
type Ref = { id: string; code: string; name?: string } | null;
type Action = {
  id: string;
  action_type: string;
  type_label: string;
  subject: string;
  priority: string;
  origin: string;
  status: string;
  status_label: string;
  late: boolean;
  due_date: string;
  responsible: { id: string; username: string; name: string } | null;
  created_by: { username: string; name: string } | null;
  created_at: string;
  closed_at: string | null;
  result: string;
  result_comment: string;
  cancel_reason: string;
  line_stop: { id: string; started_at: string } | null;
  equipment: Ref;
  lot: Ref;
  article: Ref;
};
type Prefill = { action_type?: string; subject_code?: string; line_stop?: string; lot?: string; article?: string; equipment?: string };
type Alert = {
  code: string;
  status: Status;
  title: string;
  detail: string;
  href: string;
  create: Prefill | null;
  open_action: { id: string; status: string; responsible: string | null; due_date: string; subject: string } | null;
};

const MANAGERS = ["admin", "production", "qualite"];
const ORIGINS: Record<string, string> = { saisie: "Saisie", appel_poste: "Appel au poste", alerte: "Depuis une alerte" };
const isoDay = (offset: number) => {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
const LIST_TABS = [
  { code: "open", label: "Ouvertes" },
  { code: "mine", label: "Mes actions" },
  { code: "all", label: "Toutes" },
];

export default function ActionsPage() {
  return (
    <Suspense fallback={<p>Chargement...</p>}>
      <Actions />
    </Suspense>
  );
}

function links(a: Action) {
  const parts: string[] = [];
  if (a.equipment) parts.push(`Équipement ${a.equipment.code}`);
  if (a.line_stop) parts.push(`arrêt du ${when(a.line_stop.started_at)}`);
  if (a.lot) parts.push(`lot ${a.lot.code}`);
  if (a.article) parts.push(a.article.name || a.article.code);
  return parts.join(", ");
}

function CreateForm({ options, prefill, onDone, onCancel }: { options: Options; prefill: Prefill; onDone: (a: Action) => void; onCancel: () => void }) {
  const [type, setType] = useState(prefill.action_type || "");
  const [priority, setPriority] = useState("normale");
  const [error, setError] = useState<string | null>(null);
  const subjects = options.subjects.filter((s) => s.action_type === null || s.action_type === type);
  const linked = [prefill.line_stop && "un arrêt", prefill.equipment && "un équipement", prefill.lot && "un lot", prefill.article && "un produit"].filter(Boolean);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    const payload: Record<string, unknown> = {
      action_type: type,
      subject_code: form.get("subject_code"),
      comment: form.get("comment") || "",
      priority,
      due_date: form.get("due_date"),
      responsible: form.get("responsible") || null,
      origin: prefill.action_type ? "alerte" : "saisie",
    };
    for (const key of ["line_stop", "lot", "article", "equipment"] as const) if (prefill[key]) payload[key] = prefill[key];
    try {
      onDone(await api<Action>("actions/", { method: "POST", body: JSON.stringify(payload) }));
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <form className="detail-block" onSubmit={onSubmit} style={{ display: "grid", gap: 10, maxWidth: 720 }}>
      <h2 style={{ margin: 0 }}>Nouvelle action</h2>
      {linked.length > 0 && <p className="muted" style={{ margin: 0 }}>Liée à {linked.join(", ")} (depuis l&apos;alerte ou l&apos;écran d&apos;origine).</p>}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
        <label>
          Type{" "}
          <select required value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">(choisir)</option>
            {options.types.map((t) => (
              <option key={t.code} value={t.code}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        {type && (
          <CodePicker
            key={type}
            options={subjects}
            label="Objet"
            name="subject_code"
            commentName="comment"
            initial={subjects.some((x) => x.code === prefill.subject_code) ? prefill.subject_code : ""}
          />
        )}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10, alignItems: "end" }}>
        <label>
          Priorité{" "}
          <select value={priority} onChange={(e) => setPriority(e.target.value)}>
            {options.priorities.map((p) => (
              <option key={p.code} value={p.code}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Échéance <input key={priority} type="date" name="due_date" required min={isoDay(0)} defaultValue={isoDay(priority === "haute" ? 0 : 7)} />
        </label>
        <label>
          Responsable{" "}
          <select name="responsible" defaultValue="">
            <option value="">À attribuer plus tard</option>
            {options.people.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && <p role="alert">{error}</p>}
      <span style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button type="submit">
          <Icon name="plus" size={16} />
          Créer l&apos;action
        </button>
        <button type="button" onClick={onCancel}>
          Fermer
        </button>
      </span>
    </form>
  );
}

function Step({ a, options, me, onDone }: { a: Action; options: Options; me: { id: string; role: string }; onDone: (msg: string) => void }) {
  const [open, setOpen] = useState<"assign" | "close" | "cancel" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const manager = MANAGERS.includes(me.role);
  const mine = a.responsible?.id === me.id;
  if (a.status === "terminee" || a.status === "annulee") return null;

  async function post(path: string, body: Record<string, unknown>, msg: string) {
    setError(null);
    try {
      await api<Action>(`actions/${a.id}/${path}/`, { method: "POST", body: JSON.stringify(body) });
      setOpen(null);
      onDone(msg);
    } catch (e) {
      setError(errorText(e));
    }
  }
  const submit = (path: string, msg: string, build: (f: FormData) => Record<string, unknown>) => (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    post(path, build(new FormData(event.currentTarget)), msg);
  };

  return (
    <div style={{ display: "grid", gap: 8 }}>
      <span style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {(manager || mine) && a.status === "ouverte" && (
          <button type="button" className="primary" onClick={() => post("start", {}, `Action commencée : ${a.subject}.`)}>
            Commencer
          </button>
        )}
        {(manager || mine) && (
          <button type="button" onClick={() => setOpen(open === "close" ? null : "close")}>
            <Icon name="check" size={16} />
            Terminer
          </button>
        )}
        {manager && (
          <button type="button" onClick={() => setOpen(open === "assign" ? null : "assign")}>
            <Icon name="user" size={16} />
            Attribuer
          </button>
        )}
        {manager && (
          <button type="button" onClick={() => setOpen(open === "cancel" ? null : "cancel")}>
            Annuler
          </button>
        )}
      </span>
      {open === "close" && (
        <form onSubmit={submit("close", `Action terminée : ${a.subject}.`, (f) => ({ result_code: f.get("result_code"), comment: f.get("comment") || "" }))} style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "end" }}>
          <label>
            Résultat{" "}
            <select name="result_code" required defaultValue="">
              <option value="">(choisir)</option>
              {options.results.map((r) => (
                <option key={r.code} value={r.code}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
          <button type="submit">Confirmer</button>
        </form>
      )}
      {open === "assign" && (
        <form onSubmit={submit("assign", "Action attribuée.", (f) => ({ responsible: f.get("responsible") || null }))} style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "end" }}>
          <label>
            Responsable{" "}
            <select name="responsible" defaultValue={a.responsible?.id || ""}>
              <option value="">Personne (à attribuer)</option>
              {options.people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
          <button type="submit">Confirmer</button>
        </form>
      )}
      {open === "cancel" && (
        <form onSubmit={submit("cancel", "Action annulée (elle reste visible dans « Toutes »).", (f) => ({ reason_code: f.get("reason_code"), comment: f.get("comment") || "" }))} style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "end" }}>
          <CodePicker options={options.cancel_reasons} label="Motif" name="reason_code" commentName="comment" />
          <button type="submit">Confirmer l&apos;annulation</button>
        </form>
      )}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}

function statusOf(a: Action): { status: Status; text: string } {
  if (a.status === "terminee") return { status: "ok", text: `Terminée${a.result ? `, ${a.result.toLowerCase()}` : ""}` };
  if (a.status === "annulee") return { status: "info", text: "Annulée" };
  if (a.late) return { status: "bad", text: `${a.status_label}, en retard` };
  if (!a.responsible) return { status: "warn", text: "À attribuer" };
  return { status: "info", text: a.status_label };
}

function Actions() {
  const { me } = useSession();
  const params = useSearchParams();
  const [options, setOptions] = useState<Options | null>(null);
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  const [rows, setRows] = useState<Action[] | null>(null);
  const [tab, setTab] = useState("open");
  const [prefill, setPrefill] = useState<Prefill | null>(() => {
    if (!params.get("create")) return null;
    const p: Prefill = {};
    for (const key of ["action_type", "subject_code", "line_stop", "lot", "article", "equipment"] as const) {
      const v = params.get(key);
      if (v) p[key] = v;
    }
    return p;
  });
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Options>("actions/options/").then(setOptions).catch((e) => setError(errorText(e)));
    api<Alert[]>("actions/alerts/").then(setAlerts).catch((e) => setError(errorText(e)));
    const query = tab === "mine" ? "?status=open&mine=1" : `?status=${tab}`;
    api<Action[]>(`actions/${query}`).then(setRows).catch((e) => setError(errorText(e)));
  }, [tab]);
  useEffect(() => {
    if (me) load();
  }, [me, load]);

  if (!me) return null;
  const manager = MANAGERS.includes(me.role);
  const done = (msg: string) => {
    setMessage(msg);
    load();
  };

  return (
    <main>
      <h1>Actions</h1>
      <p style={{ maxWidth: 820 }}>
        Un écart, un arrêt ou un lot bloqué appelle une action : qui s&apos;en charge, pour quand. Les alertes ci-dessous sont recalculées à chaque affichage et disent si une action
        ouverte les couvre déjà.
      </p>
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}
      {error && <p role="alert">{error}</p>}

      {manager && options && (prefill ? (
        <CreateForm
          key={JSON.stringify(prefill)}
          options={options}
          prefill={prefill}
          onCancel={() => setPrefill(null)}
          onDone={(a) => {
            setPrefill(null);
            done(`Action créée : ${a.subject}, échéance le ${day(a.due_date)}${a.responsible ? `, pour ${a.responsible.name}` : ", à attribuer"}.`);
          }}
        />
      ) : (
        <p>
          <button type="button" className="primary" onClick={() => setPrefill({})}>
            <Icon name="plus" size={16} />
            Nouvelle action
          </button>
        </p>
      ))}

      <section className="detail-block">
        <h3 className="detail-answer">{alerts === null ? "Alertes" : alerts.length ? `${alerts.length} alerte(s), la plus grave d'abord` : "Aucune alerte en ce moment"}</h3>
        <div style={{ display: "grid", gap: 10 }}>
          {(alerts || []).map((al, i) => (
            <div key={i} className="stop-card">
              <span style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                <StatusBadge status={al.status} text={al.status === "bad" ? "Rouge" : "Jaune"} />
                <strong>{al.title}</strong>
              </span>
              <span className="muted">{al.detail}</span>
              <span style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                {al.open_action ? (
                  <span style={{ display: "inline-flex", gap: 6, alignItems: "flex-start", color: "var(--text-2)" }}>
                    <Icon name="circle-check" size={16} />
                    <span>
                      Action {al.open_action.status.toLowerCase()} : {al.open_action.subject}, {al.open_action.responsible || "à attribuer"}, pour le {day(al.open_action.due_date)}
                    </span>
                  </span>
                ) : (
                  al.create && manager && (
                    <button type="button" className="primary" onClick={() => setPrefill(al.create)}>
                      <Icon name="plus" size={16} />
                      Créer une action
                    </button>
                  )
                )}
                <Link href={al.href} className="btn-link">
                  <Icon name="search" size={16} />
                  Voir
                </Link>
              </span>
            </div>
          ))}
        </div>
      </section>

      <div className="tab-row" role="tablist" aria-label="Actions affichées">
        {LIST_TABS.map((t) => (
          <button key={t.code} type="button" role="tab" aria-selected={t.code === tab} className={t.code === tab ? "tab active" : "tab"} onClick={() => setTab(t.code)}>
            {t.label}
          </button>
        ))}
      </div>
      {rows === null && <p>Chargement...</p>}
      {rows && rows.length === 0 && <p className="muted">Aucune action.</p>}
      <div style={{ display: "grid", gap: 10 }}>
        {(rows || []).map((a) => {
          const s = statusOf(a);
          return (
            <div key={a.id} className="stop-card">
              <span style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
                <StatusBadge status={s.status} text={s.text} />
                <strong>{a.subject}</strong>
                <span className="muted">
                  {a.type_label}
                  {a.priority === "haute" ? ", priorité haute" : ""}
                </span>
              </span>
              <span>
                Échéance {day(a.due_date)} · {a.responsible ? a.responsible.name : "À attribuer"} · {ORIGINS[a.origin] || a.origin} par {a.created_by?.name || "inconnu"}, le {when(a.created_at)}
              </span>
              {links(a) && <span className="muted">{links(a)}</span>}
              {a.status === "annulee" && a.cancel_reason && <span className="muted">Motif d&apos;annulation : {a.cancel_reason}</span>}
              {options && <Step a={a} options={options} me={me} onDone={done} />}
            </div>
          );
        })}
      </div>
    </main>
  );
}
