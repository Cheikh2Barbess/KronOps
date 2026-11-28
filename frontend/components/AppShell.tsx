"use client";

// Mise en page commune : bandeau en haut, menu a gauche, ecran choisi a droite.
// Le menu respecte les droits par role et masque les modules desactives dans l'ecran Pipeline.
// Ce composant ne fait que de l'affichage : chaque ecran garde ses propres controles d'acces,
// et l'API refuse de toute facon ce que le role ne permet pas.
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ReactNode, createContext, useContext, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";

export type Me = { username: string; first_name?: string; last_name?: string; role: string; tenant_name: string };

// Nom affiche dans le bandeau : prenom et nom de la fiche, sinon l'identifiant.
function displayName(me: Me) {
  return [me.first_name, me.last_name].map((s) => (s || "").trim()).filter(Boolean).join(" ") || me.username;
}
type Health = { status: string; database: string };
type PipelineBlock = { steps: { code: string; is_active: boolean }[] };

type Session = {
  // undefined = verification en cours, null = pas connecte.
  me: Me | null | undefined;
  setMe: (me: Me | null) => void;
};

const SessionContext = createContext<Session>({ me: undefined, setMe: () => {} });

export function useSession() {
  return useContext(SessionContext);
}

const ROLE_LABELS: Record<string, string> = {
  admin: "Administrateur",
  qualite: "Qualité",
  production: "Production",
  operateur: "Opérateur",
  lecture: "Lecture",
};

type NavItem = { href: string; label: string; hint: string; roles?: string[]; module?: string };

// L'ordre suit le parcours du produit. Les roles reprennent ceux de l'ancien accueil, sans changement.
// Emplacement prevu : une entree « Tableau de bord » (href "/dashboard") viendra en tete de liste
// et deviendra l'ecran ouvert par defaut a la connexion. Elle n'existe pas encore.
const NAV: NavItem[] = [
  { href: "/referentiels", label: "Référentiels", hint: "Articles, fournisseurs, clients, parcelles, sites et équipements" },
  { href: "/pipeline", label: "Pipeline", hint: "Les 8 blocs, du producteur au conteneur" },
  { href: "/tracabilite", label: "Traçabilité", hint: "Recherche amont et aval", roles: ["admin", "qualite", "production", "lecture"] },
  { href: "/receptions", label: "Réceptions", hint: "Enregistrer une livraison", roles: ["admin", "qualite", "production", "operateur"] },
  { href: "/production", label: "Production", hint: "Déclarer une étape (mûrissement, séchage, cartons, palette)", roles: ["admin", "production", "operateur"] },
  { href: "/transferts", label: "Transferts", hint: "Envoyer un lot vers une autre usine", roles: ["admin", "production", "operateur"], module: "transfert" },
  { href: "/qualite", label: "Contrôle qualité", hint: "Contrôle qualité d'un lot", roles: ["admin", "qualite"] },
  { href: "/expeditions", label: "Expéditions", hint: "Conteneur, plomb, certificat d'inspection", roles: ["admin", "production"], module: "expedition" },
  { href: "/bilan", label: "Bilan matière", hint: "Rendements et écarts", roles: ["admin", "qualite", "production", "lecture"] },
  { href: "/rappel", label: "Rappel", hint: "Rapport de rappel depuis un carton, une palette ou un conteneur", roles: ["admin", "qualite", "production", "lecture"] },
  { href: "/validations", label: "Validations", hint: "Déblocage, destruction, rebut, ajustement", roles: ["admin", "qualite", "production", "operateur"] },
  { href: "/journal", label: "Journal d'audit", hint: "Qui a fait quoi, et quand", roles: ["admin", "qualite"] },
  { href: "/utilisateurs", label: "Utilisateurs", hint: "Créer, modifier, désactiver", roles: ["admin"] },
];

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [health, setHealth] = useState<Health | null>(null);
  // Modules facultatifs desactives dans l'ecran Pipeline : leur bouton n'est pas affiche.
  const [off, setOff] = useState<string[]>([]);
  // Hauteur reelle du bandeau : le menu de gauche se fige juste en dessous, meme si le bandeau passe sur deux lignes.
  const topbar = useRef<HTMLElement>(null);
  const [topbarHeight, setTopbarHeight] = useState(0);

  useEffect(() => {
    api<Health>("health/").then(setHealth).catch(() => setHealth({ status: "injoignable", database: "?" }));
    api<Me>("auth/me/").then(setMe).catch(() => setMe(null));
  }, []);

  // Relu a chaque changement d'ecran : un module coche ou decoche dans Pipeline apparait aussitot.
  useEffect(() => {
    if (!me) return;
    api<PipelineBlock[]>("production/pipeline/")
      .then((blocks) => setOff(blocks.flatMap((b) => b.steps).filter((s) => !s.is_active).map((s) => s.code)))
      .catch(() => setOff([]));
  }, [me, pathname]);

  useEffect(() => {
    const el = topbar.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setTopbarHeight(el.offsetHeight));
    observer.observe(el);
    return () => observer.disconnect();
  }, [me]);

  async function onLogout() {
    await api("auth/logout/", { method: "POST" }).catch(() => null);
    setMe(null);
    router.push("/");
  }

  const session = { me, setMe };

  if (!me) {
    // Pas connecte (ou verification en cours) : pas de menu, seulement le nom et l'ecran demande.
    return (
      <SessionContext.Provider value={session}>
        <div className="shell-guest">
          <Link href="/" className="brand brand-guest">Tracalys</Link>
          <p className="guest-status">
            Service : <strong>{health ? health.status : "..."}</strong>, base de données : <strong>{health ? health.database : "..."}</strong>
          </p>
          {children}
        </div>
      </SessionContext.Provider>
    );
  }

  const items = NAV.filter((i) => (!i.roles || i.roles.includes(me.role)) && (!i.module || !off.includes(i.module)));
  const healthy = health?.status === "ok" && health?.database === "ok";

  return (
    <SessionContext.Provider value={session}>
      <div className="shell" style={{ ["--topbar-h" as string]: `${topbarHeight}px` }}>
        <header ref={topbar} className="topbar no-print">
          <Link href="/" className="brand">
            Tracalys
          </Link>
          <span className="company">{me.tenant_name}</span>
          <span className="spacer" />
          <span className="status" title={health ? `Service : ${health.status}, base de données : ${health.database}` : "Vérification..."}>
            <span className={`dot ${health ? (healthy ? "ok" : "ko") : ""}`} />
            {health ? (healthy ? "Service et base OK" : "Service ou base en défaut") : "..."}
          </span>
          <span className="user">
            <strong>{displayName(me)}</strong> <span className="role">{ROLE_LABELS[me.role] || me.role}</span>
          </span>
          <button type="button" className="logout" onClick={onLogout}>
            Se déconnecter
          </button>
        </header>
        <nav className="sidebar no-print" aria-label="Menu principal">
          {items.map((i) => {
            const active = pathname === i.href || pathname.startsWith(`${i.href}/`);
            return (
              <Link key={i.href} href={i.href} title={i.hint} className={`navbtn${active ? " active" : ""}`} aria-current={active ? "page" : undefined}>
                {i.label}
              </Link>
            );
          })}
        </nav>
        <div className="content">{children}</div>
      </div>
    </SessionContext.Provider>
  );
}
