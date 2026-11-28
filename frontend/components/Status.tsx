"use client";

// Code couleur commun a tout Tracalys : vert (OK), jaune (a surveiller), rouge (non OK), gris (information).
// Jamais la couleur seule : chaque etat a aussi une icone de forme differente et un mot (lisible par un daltonien
// et a l'impression en noir et blanc).
export type Status = "ok" | "warn" | "bad" | "info";

export const STATUS_META: Record<Status, { label: string; icon: string; fg: string; bg: string; border: string }> = {
  ok: { label: "OK", icon: "✓", fg: "#1b5e20", bg: "#e8f5e9", border: "#2e7d32" },
  warn: { label: "À surveiller", icon: "!", fg: "#6d4500", bg: "#fff4d6", border: "#c98a00" },
  bad: { label: "Non OK", icon: "✕", fg: "#a3001b", bg: "#fdecea", border: "#c62828" },
  info: { label: "Information", icon: "i", fg: "#374151", bg: "#eef1f4", border: "#9ca3af" },
};

export function StatusIcon({ status }: { status: Status }) {
  const m = STATUS_META[status] || STATUS_META.info;
  return (
    <span className="status-icon" aria-hidden="true" style={{ background: m.border }}>
      {m.icon}
    </span>
  );
}

// Pastille : icone + texte. `text` remplace le mot par defaut (ex. « Bloqué », « Conforme »).
export function StatusBadge({ status, text, title }: { status: Status; text?: string; title?: string }) {
  const m = STATUS_META[status] || STATUS_META.info;
  return (
    <span className="status-badge" title={title} style={{ color: m.fg, background: m.bg, borderColor: m.border }}>
      <StatusIcon status={status} />
      {text || m.label}
    </span>
  );
}

// Etats deja connus des ecrans, convertis dans le code couleur (regles fixes, sans seuil).
export const LOT_STATUS: Record<string, { status: Status; text: string }> = {
  disponible: { status: "ok", text: "Disponible" },
  bloque: { status: "bad", text: "Bloqué" },
  detruit: { status: "info", text: "Détruit" },
};

export function LotStatusBadge({ status }: { status: string }) {
  const s = LOT_STATUS[status];
  return s ? <StatusBadge status={s.status} text={s.text} /> : <>{status}</>;
}

export function QcBadge({ result }: { result: string }) {
  return result === "conforme" ? <StatusBadge status="ok" text="Conforme" /> : <StatusBadge status="bad" text="Non conforme" />;
}

// Documents d'une expedition : meme regle que le tableau de bord (dashboard/selectors.py, shipment_documents).
export function shipmentDocs(s: { export_document_ref: string; bill_of_lading: string; container_number: string; seal_number: string }, organic: boolean): { status: Status; text: string } {
  if (organic && !s.export_document_ref) return { status: "bad", text: "COI manquant (produit bio)" };
  const missing = [];
  if (s.container_number && !s.seal_number) missing.push("plomb");
  if (!s.bill_of_lading) missing.push("BL");
  if (missing.length) return { status: "warn", text: `Manque : ${missing.join(", ")}` };
  return { status: "ok", text: "Documents complets" };
}
