"use client";

// Briques communes des ecrans : listes codees (regle du projet : le moins de texte libre possible),
// statut bio, saisie tardive. La precision libre n'apparait que pour « Autre ».
import { useState } from "react";
import { ApiError } from "@/lib/api";

export type Option = { code: string; label: string };

export const ORGANIC: Record<string, string> = { bio: "Bio", conversion: "En conversion", conventionnel: "Conventionnel" };
const ORGANIC_COLOR: Record<string, string> = { bio: "#1b5e20", conversion: "#8a5a00", conventionnel: "var(--muted)" };

export function OrganicBadge({ status }: { status: string }) {
  if (!status) return null;
  return (
    <span
      style={{
        border: `1px solid ${ORGANIC_COLOR[status] || "var(--muted)"}`,
        color: ORGANIC_COLOR[status] || "var(--muted)",
        borderRadius: 4,
        padding: "0 4px",
        fontSize: "0.85em",
        whiteSpace: "nowrap",
      }}
    >
      {ORGANIC[status] || status}
    </span>
  );
}

export function unitLabel(unit: string, quantity?: string | number | null): string {
  if (unit === "l") return "L";
  if (unit === "unite") return quantity !== undefined && quantity !== null && Math.abs(Number(quantity)) > 1 ? "unités" : "unité";
  return unit;
}
export const fmt = (n: string | number) => Number(n).toLocaleString("fr-FR", { maximumFractionDigits: 3 });
export const withUnit = (n: string | number, unit: string) => `${fmt(n)} ${unitLabel(unit, n)}`;
export const when = (d: string) => new Date(d).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
export const day = (d: string) => new Date(d).toLocaleDateString("fr-FR");

export function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 403) return "Votre rôle ne permet pas cette action.";
    if (e.body && typeof e.body === "object" && "detail" in e.body) return String((e.body as { detail: string }).detail);
    if (e.body && typeof e.body === "object")
      return Object.values(e.body as Record<string, unknown>)
        .map((v) => (Array.isArray(v) ? v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(" ") : String(v)))
        .join(" ");
  }
  return "Erreur.";
}

// Liste fermee avec precision obligatoire pour « Autre ». Les noms des champs du formulaire sont parametrables.
export function CodePicker({
  options,
  label,
  name,
  commentName,
  required = true,
}: {
  options: Option[];
  label: string;
  name: string;
  commentName: string;
  required?: boolean;
}) {
  const [code, setCode] = useState("");
  return (
    <>
      <label>
        {label}{" "}
        <select name={name} required={required} value={code} onChange={(e) => setCode(e.target.value)}>
          <option value="">(choisir)</option>
          {options.map((o) => (
            <option key={o.code} value={o.code}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
      {code === "autre" && (
        <label>
          Précisez <input name={commentName} required style={{ width: 220 }} />
        </label>
      )}
    </>
  );
}

// Saisie au moment du geste. Par defaut : l'heure du serveur. Cocher seulement pour une saisie faite apres coup.
export function LateEntry({ reasons, label = "Date et heure réelles" }: { reasons: Option[]; label?: string }) {
  const [late, setLate] = useState(false);
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
      <label>
        <input type="checkbox" checked={late} onChange={(e) => setLate(e.target.checked)} /> Saisie après coup (le geste a eu lieu
        plus tôt)
      </label>
      {late && (
        <>
          <label>
            {label} <input type="datetime-local" name="occurred_at" required />
          </label>
          <CodePicker options={reasons} label="Pourquoi ?" name="late_reason_code" commentName="late_comment" />
          <small style={{ color: "#8a5a00" }}>Au-delà de 2 heures, la saisie reste signalée comme tardive.</small>
        </>
      )}
    </div>
  );
}

export function lateFields(form: FormData): Record<string, string> {
  const occurred = String(form.get("occurred_at") || "");
  if (!occurred) return {};
  return {
    occurred_at: new Date(occurred).toISOString(),
    late_reason_code: String(form.get("late_reason_code") || ""),
    late_comment: String(form.get("late_comment") || ""),
  };
}

export function LateFlag({ late }: { late: boolean }) {
  return late ? (
    <span title="Saisie faite plus de 2 heures après le geste" style={{ color: "#8a5a00", whiteSpace: "nowrap" }}>
      ⚠ saisie tardive
    </span>
  ) : null;
}
