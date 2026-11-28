"use client";

// Code couleur commun a tout Tracalys : vert (OK), jaune (a surveiller), rouge (non OK), gris (information).
// Jamais la couleur seule : chaque etat a aussi une icone de forme differente et un mot (lisible par un daltonien
// et a l'impression en noir et blanc).
import { Icon, IconName } from "@/components/Icon";

export type Status = "ok" | "warn" | "bad" | "info";

// fg : texte (contraste AA sur bg). solid : icone et barres.
export const STATUS_META: Record<Status, { label: string; icon: IconName; fg: string; bg: string; border: string }> = {
  ok: { label: "OK", icon: "circle-check", fg: "#085d3a", bg: "#ecfdf3", border: "#079455" },
  warn: { label: "À surveiller", icon: "triangle-alert", fg: "#7a2e0e", bg: "#fffaeb", border: "#dc6803" },
  bad: { label: "Non OK", icon: "octagon-x", fg: "#912018", bg: "#fef3f2", border: "#d92d20" },
  info: { label: "Information", icon: "info", fg: "#344054", bg: "#f2f4f7", border: "#667085" },
};

export function StatusIcon({ status, size = 15 }: { status: Status; size?: number }) {
  const m = STATUS_META[status] || STATUS_META.info;
  return (
    <span className="status-icon" aria-hidden="true" style={{ color: m.border }}>
      <Icon name={m.icon} size={size} />
    </span>
  );
}

// Pastille : icone + texte. `text` remplace le mot par defaut (ex. « Bloqué », « Conforme »).
export function StatusBadge({ status, text, title }: { status: Status; text?: string; title?: string }) {
  const m = STATUS_META[status] || STATUS_META.info;
  return (
    <span className="status-badge" title={title} style={{ color: m.fg, background: m.bg }}>
      <StatusIcon status={status} size={14} />
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
