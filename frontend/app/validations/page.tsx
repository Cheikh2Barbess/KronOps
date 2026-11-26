"use client";

// Double validation (US-20) : deblocage, destruction, rebut et ajustement de stock.
// Une personne demande, une 2e personne d'un AUTRE role valide. Les regles sont appliquees par l'API.
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";

type Me = { id: string; username: string; role: string };
type Lot = {
  id: string;
  code: string;
  article_code: string;
  article_name: string;
  base_unit: string;
  supplier_lot_code: string;
  status: string;
  block_reason: string;
  balance: string;
  expired: boolean;
};
type Approval = {
  id: string;
  action: string;
  lot_code: string;
  lot_status: string;
  article_name: string;
  base_unit: string;
  quantity: string | null;
  reason: string;
  status: string;
  requested_by_username: string;
  requested_role: string;
  decided_by_username: string | null;
  decided_role: string;
  decided_at: string | null;
  decision_comment: string;
  created_at: string;
};

const ACTIONS: Record<string, string> = {
  release: "Débloquer le lot",
  destroy: "Détruire le lot",
  scrap: "Rebut ou perte",
  adjust: "Ajustement de stock",
};
const STATUS: Record<string, string> = { pending: "En attente", approved: "Validée", rejected: "Refusée", cancelled: "Annulée" };
const LOT_STATUS: Record<string, string> = { disponible: "Disponible", bloque: "Bloqué", detruit: "Détruit" };
const ROLES: Record<string, string> = {
  admin: "Admin", qualite: "Qualité", production: "Production", operateur: "Opérateur", lecture: "Lecture",
};
// Matrice des droits du PRD (rappel a l'ecran, l'API reste juge).
const CAN_REQUEST: Record<string, string[]> = {
  release: ["qualite"],
  destroy: ["qualite"],
  scrap: ["qualite", "production", "operateur"],
  adjust: ["qualite", "production"],
};
const CAN_VALIDATE = ["admin", "qualite", "production"];
const CAN_BLOCK = ["admin", "qualite", "production"];

const fmt = (n: string) => Number(n).toLocaleString("fr-FR", { maximumFractionDigits: 3 });
const when = (d: string) => new Date(d).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });

function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403 && e.body && typeof e.body === "object" && "detail" in e.body) return String((e.body as { detail: string }).detail);
    if (e.body && typeof e.body === "object")
      return Object.values(e.body as Record<string, unknown>)
        .map((v) => (Array.isArray(v) ? v.join(" ") : String(v)))
        .join(" ");
  }
  return "Erreur.";
}

function LotPanel({ lot, me, onChanged }: { lot: Lot; me: Me; onChanged: (message: string) => void }) {
  const allowed = Object.keys(ACTIONS).filter((a) => CAN_REQUEST[a].includes(me.role));
  const [action, setAction] = useState(allowed[0] || "");
  const [error, setError] = useState<string | null>(null);

  async function onRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    const quantity = String(form.get("quantity") || "").replace(",", ".").trim();
    try {
      await api("approvals/", {
        method: "POST",
        body: JSON.stringify({ action, lot: lot.id, reason: form.get("reason"), quantity: quantity || null }),
      });
      onChanged(`Demande « ${ACTIONS[action]} » envoyée. Elle attend la validation d'une personne d'un autre rôle.`);
    } catch (e) {
      setError(errorText(e));
    }
  }

  async function onBlock(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    const form = new FormData(event.currentTarget);
    try {
      await api(`lots/${lot.id}/block/`, { method: "POST", body: JSON.stringify({ reason: form.get("block_reason") }) });
      onChanged(`Lot ${lot.code} bloqué.`);
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <div style={{ border: "1px solid #888", padding: 12, margin: "8px 0" }}>
      <p>
        <strong>{lot.code}</strong> · {lot.article_code} {lot.article_name} · lot fournisseur {lot.supplier_lot_code || "(aucun)"} ·{" "}
        <strong>{LOT_STATUS[lot.status] || lot.status}</strong>
        {lot.expired && " · périmé"} · en stock : {fmt(lot.balance)} {lot.base_unit}
        {lot.block_reason && <> · motif du blocage : {lot.block_reason}</>}
      </p>
      {lot.status === "disponible" && CAN_BLOCK.includes(me.role) && (
        <form onSubmit={onBlock} style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8 }}>
          <label>
            Motif du blocage <input name="block_reason" required style={{ width: 280 }} />
          </label>
          <button type="submit">Bloquer ce lot</button>
          <span style={{ color: "#555" }}>(immédiat, sans double validation)</span>
        </form>
      )}
      {lot.status !== "detruit" && allowed.length > 0 && (
        <form onSubmit={onRequest} style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
          <label>
            Demander{" "}
            <select name="action" value={action} onChange={(e) => setAction(e.target.value)}>
              {allowed.map((a) => (
                <option key={a} value={a}>
                  {ACTIONS[a]}
                </option>
              ))}
            </select>
          </label>
          {(action === "scrap" || action === "adjust") && (
            <label>
              Quantité ({lot.base_unit}){" "}
              <input name="quantity" required inputMode="decimal" style={{ width: 100 }}
                placeholder={action === "adjust" ? "ex. -2,5 ou 3" : "ex. 2,5"} />
            </label>
          )}
          <label>
            Motif <input name="reason" required style={{ width: 280 }} />
          </label>
          <button type="submit">Envoyer la demande</button>
        </form>
      )}
      {lot.status !== "detruit" && allowed.length === 0 && <p>Votre rôle ne permet pas de demander ces actions.</p>}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}

function ApprovalRow({ a, me, onChanged }: { a: Approval; me: Me; onChanged: (message: string) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState(false);
  const mine = a.requested_by_username === me.username;
  const canDecide = a.status === "pending" && !mine && CAN_VALIDATE.includes(me.role) && a.requested_role !== me.role;

  async function decide(verb: "approve" | "reject" | "cancel", comment = "") {
    setError(null);
    try {
      await api(`approvals/${a.id}/${verb}/`, { method: "POST", body: JSON.stringify({ comment }) });
      onChanged(verb === "approve" ? "Demande validée : l'action est faite." : verb === "reject" ? "Demande refusée." : "Demande annulée.");
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <tr style={{ borderTop: "1px solid #ddd", verticalAlign: "top" }}>
      <td>{when(a.created_at)}</td>
      <td>{ACTIONS[a.action] || a.action}</td>
      <td>
        {a.lot_code}
        <br />
        <small>{a.article_name}</small>
      </td>
      <td>{a.quantity !== null ? `${fmt(a.quantity)} ${a.base_unit}` : ""}</td>
      <td>{a.reason}</td>
      <td>
        {a.requested_by_username} ({ROLES[a.requested_role] || a.requested_role})
      </td>
      <td>
        <strong>{STATUS[a.status] || a.status}</strong>
        {a.decided_by_username && (
          <>
            <br />
            <small>
              par {a.decided_by_username} ({ROLES[a.decided_role] || a.decided_role})
              {a.decision_comment && ` : ${a.decision_comment}`}
            </small>
          </>
        )}
      </td>
      <td>
        {canDecide && !rejecting && (
          <>
            <button onClick={() => decide("approve")}>Valider</button> <button onClick={() => setRejecting(true)}>Refuser</button>
          </>
        )}
        {canDecide && rejecting && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              decide("reject", String(new FormData(e.currentTarget).get("comment") || ""));
            }}
          >
            <input name="comment" required placeholder="Raison du refus" />{" "}
            <button type="submit">Confirmer le refus</button>{" "}
            <button type="button" onClick={() => setRejecting(false)}>
              Annuler
            </button>
          </form>
        )}
        {a.status === "pending" && mine && <button onClick={() => decide("cancel")}>Annuler ma demande</button>}
        {a.status === "pending" && !mine && !canDecide && <small>À valider par un autre rôle</small>}
        {error && <p role="alert">{error}</p>}
      </td>
    </tr>
  );
}

export default function Validations() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [lots, setLots] = useState<Lot[] | null>(null);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [showAll, setShowAll] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);

  const loadApprovals = useCallback(() => {
    api<Approval[]>(showAll ? "approvals/" : "approvals/?status=pending")
      .then(setApprovals)
      .catch((e) => setError(errorText(e)));
  }, [showAll]);

  useEffect(() => {
    api<Me>("auth/me/").then(setMe).catch(() => setMe(null));
  }, []);
  useEffect(() => {
    if (me) loadApprovals();
  }, [me, loadApprovals]);

  async function findLots(term: string) {
    if (!term.trim()) return setLots(null);
    try {
      setLots(await api<Lot[]>(`lots/?search=${encodeURIComponent(term.trim())}`));
    } catch (e) {
      setError(errorText(e));
    }
  }

  function changed(text: string) {
    setMessage(text);
    loadApprovals();
    findLots(search);
  }

  if (me === undefined) return <main><p>Chargement...</p></main>;
  if (me === null || me.role === "lecture")
    return (
      <main>
        <p role="alert">{me === null ? "Connectez-vous d'abord." : "La double validation n'est pas ouverte au rôle Lecture."}</p>
        <a href="/">Accueil</a>
      </main>
    );

  return (
    <main>
      <p>
        <a href="/">Accueil</a>
      </p>
      <h1>Validations</h1>
      <p>
        Déblocage, destruction, rebut et ajustement de stock demandent l&apos;accord de deux personnes : l&apos;une demande, une
        autre d&apos;un rôle différent valide. Vous êtes <strong>{me.username}</strong> ({ROLES[me.role] || me.role}).
      </p>
      {message && <p style={{ background: "#e8f5e9", padding: 8 }}>{message}</p>}
      {error && <p role="alert">{error}</p>}

      <h2>Faire une demande sur un lot</h2>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          findLots(search);
        }}
      >
        <label>
          Code du lot ou lot fournisseur{" "}
          <input name="lot_search" value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: 280 }} />
        </label>{" "}
        <button type="submit">Chercher</button>
      </form>
      {lots !== null && lots.length === 0 && <p>Aucun lot trouvé.</p>}
      {lots?.slice(0, 10).map((lot) => (
        <LotPanel key={lot.id} lot={lot} me={me} onChanged={changed} />
      ))}

      <h2>{showAll ? "Toutes les demandes" : "Demandes en attente"}</h2>
      <label>
        <input type="checkbox" name="show_all" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> Afficher aussi
        les demandes traitées
      </label>
      {approvals.length === 0 ? (
        <p>Aucune demande.</p>
      ) : (
        <table cellPadding={4} style={{ borderCollapse: "collapse", width: "100%" }}>
          <thead>
            <tr style={{ textAlign: "left" }}>
              <th>Date</th>
              <th>Action</th>
              <th>Lot</th>
              <th>Quantité</th>
              <th>Motif</th>
              <th>Demandé par</th>
              <th>Statut</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {approvals.map((a) => (
              <ApprovalRow key={a.id} a={a} me={me} onChanged={changed} />
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
