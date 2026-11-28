// Seuils des couleurs (reglables par l'Admin, ecran /dashboard/seuils).
export type Threshold = { code: string; label: string; unit: string; direction: string; green: number | string; red: number | string; is_default: boolean };

const num = (n: number | string) => Number(n).toLocaleString("fr-FR", { maximumFractionDigits: 2 });

export function thresholdText(t: Threshold) {
  const u = t.unit === "%" ? " %" : ` ${t.unit}`;
  const rule =
    t.direction === "higher"
      ? `vert à partir de ${num(t.green)}${u}, rouge sous ${num(t.red)}${u}, jaune entre les deux`
      : `vert jusqu'à ${num(t.green)}${u}, rouge au-delà de ${num(t.red)}${u}, jaune entre les deux`;
  return `${rule}${t.is_default ? " (seuil par défaut)" : " (seuil réglé par l'entreprise)"}`;
}
