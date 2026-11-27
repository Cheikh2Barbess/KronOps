"use client";

// Affichage commun d'une declaration d'etape (ecran Production, bilan matiere, rappel).
import { fmt } from "@/components/Codes";

export type Run = {
  id: string;
  step: string;
  step_label: string;
  equipment_code: string | null;
  equipment_name: string | null;
  site_name: string | null;
  output_lot_code: string;
  output_article_code: string;
  output_article_name: string;
  organic_status: string;
  base_unit: string;
  inputs: { lot_code: string; article_code: string; quantity: string; base_unit: string; parcel_code: string | null; organic_status: string }[];
  input_quantity: string;
  output_quantity: string;
  waste_quantity: string;
  waste_label: string;
  unexplained_quantity: string | null;
  yield_pct: string | null;
  yield_min_pct: string | null;
  yield_max_pct: string | null;
  yield_status: string;
  ended_at: string;
  late: boolean;
  late_reason_label: string;
  username: string | null;
  cancellable?: boolean | null;
  cancelled: { at: string; by: string | null; reason_code: string; reason: string } | null;
};

export function YieldCell({ run }: { run: Run }) {
  if (run.cancelled)
    return (
      <span style={{ color: "#b00020" }}>
        <strong>Annulée</strong>
        <br />
        <small>{run.cancelled.reason}</small>
      </span>
    );
  if (run.yield_pct === null) return <span>sans objet</span>;
  const ratio = Number(run.yield_pct) > 0 ? 100 / Number(run.yield_pct) : null;
  const color = run.yield_status === "conforme" ? "#1b5e20" : run.yield_status === "sans_reference" ? "#555" : "#b00020";
  const label =
    run.yield_status === "bas" ? "sous la fourchette" : run.yield_status === "haut" ? "au-dessus de la fourchette" : run.yield_status === "conforme" ? "dans la fourchette" : "pas de référence";
  return (
    <span style={{ color }}>
      <strong>{fmt(run.yield_pct)} %</strong>
      {ratio && Number(run.yield_pct) < 50 ? ` (${fmt(ratio.toFixed(1))} pour 1)` : ""}
      <br />
      <small>
        {label}
        {run.yield_min_pct ? ` ${fmt(run.yield_min_pct)} à ${fmt(run.yield_max_pct || "")} %` : ""}
      </small>
    </span>
  );
}

