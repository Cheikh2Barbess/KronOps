"use client";

// Pipeline fruits seches export en 8 blocs : chaque etape de l'etude et ou elle se fait dans Tracalys.
// Etape de production et ecran facultatif : activables par l'Admin (verifie par l'API).
// Ecran obligatoire (tracabilite) et etape prevue (pas encore construite) : non modifiables.
import { useCallback, useEffect, useState } from "react";
import { errorText } from "@/components/Codes";
import { api } from "@/lib/api";

type Step = {
  code: string;
  label: string;
  kind: "transformation" | "obligatoire" | "module" | "prevu";
  kind_label: string;
  path: string | null;
  phase: string | null;
  is_active: boolean;
  locked: boolean;
};
type Block = { number: number; label: string; steps: Step[] };

const KIND_COLOR: Record<string, string> = {
  transformation: "#1b5e20",
  obligatoire: "#0d47a1",
  module: "#6a1b9a",
  prevu: "#777",
};

export default function PipelinePage() {
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [changes, setChanges] = useState<Record<string, boolean>>({});
  const [isAdmin, setIsAdmin] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    api<Block[]>("production/pipeline/").then(setBlocks).catch((e) => setError(errorText(e)));
  }, []);
  useEffect(load, [load]);
  useEffect(() => {
    api<{ role: string }>("auth/me/")
      .then((me) => setIsAdmin(me.role === "admin"))
      .catch(() => setIsAdmin(false));
  }, []);

  const activeOf = (s: Step) => (s.code in changes ? changes[s.code] : s.is_active);
  function toggle(s: Step) {
    setMessage(null);
    const next = !activeOf(s);
    setChanges((old) => {
      const copy = { ...old };
      if (next === s.is_active) delete copy[s.code];
      else copy[s.code] = next;
      return copy;
    });
  }
  async function save() {
    setError(null);
    try {
      const saved = await api<Block[]>("production/pipeline/", {
        method: "PUT",
        body: JSON.stringify({ steps: Object.entries(changes).map(([code, is_active]) => ({ code, is_active })) }),
      });
      setBlocks(saved);
      setChanges({});
      setMessage("Pipeline enregistré.");
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <main>
      <h1>Pipeline : du producteur au conteneur</h1>
      <p style={{ maxWidth: 760, color: "#555" }}>
        Les 8 blocs du pipeline des fruits séchés export. Cochez ce que votre entreprise utilise. Une étape de production
        décochée n&apos;est plus proposée à la déclaration. Un écran facultatif décoché disparaît de l&apos;accueil et
        l&apos;API le refuse. Les écrans de traçabilité restent toujours actifs. Les étapes « prévues » ne sont pas encore
        construites : leur phase est indiquée. L&apos;ordre des étapes de production se règle dans{" "}
        <a href="/referentiels">Référentiels</a>, les étapes par produit aussi (parcours).
      </p>
      <p style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
        {["transformation", "obligatoire", "module", "prevu"].map((k) => (
          <span key={k} style={{ color: KIND_COLOR[k] }}>
            ■ {blocks.flatMap((b) => b.steps).find((s) => s.kind === k)?.kind_label || k}
          </span>
        ))}
      </p>
      {blocks.map((b) => (
        <section key={b.number} style={{ border: "1px solid #888", padding: "8px 12px", margin: "10px 0", maxWidth: 760 }}>
          <h2 style={{ fontSize: "1.1em", margin: "4px 0 8px" }}>
            {b.number}. {b.label}
          </h2>
          {b.steps.map((s) => (
            <div key={s.code} style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", padding: "3px 0" }}>
              <label style={{ opacity: s.kind === "prevu" ? 0.6 : 1 }}>
                <input type="checkbox" checked={activeOf(s)} disabled={!isAdmin || s.locked} onChange={() => toggle(s)} />{" "}
                {s.label}
              </label>
              <small style={{ color: KIND_COLOR[s.kind] }}>
                {s.kind_label}
                {s.phase ? ` · ${s.phase}` : ""}
              </small>
              {s.path && s.kind !== "prevu" && activeOf(s) && (
                <small>
                  <a href={s.path}>ouvrir</a>
                </small>
              )}
            </div>
          ))}
        </section>
      ))}
      {isAdmin ? (
        <p>
          <button type="button" onClick={save} disabled={Object.keys(changes).length === 0}>
            Enregistrer le pipeline
          </button>
        </p>
      ) : (
        <p style={{ color: "#555" }}>Seul l&apos;administrateur de l&apos;entreprise peut modifier le pipeline.</p>
      )}
      {message && <p role="status">{message}</p>}
      {error && (
        <p role="alert" style={{ color: "#b00020" }}>
          {error}
        </p>
      )}
    </main>
  );
}
