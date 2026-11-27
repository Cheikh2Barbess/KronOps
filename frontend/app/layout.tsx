import type { ReactNode } from "react";

export const metadata = { title: "Tracalys" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="fr">
      <head>
        {/* Impression des rapports (rappel, bilan) : les filtres et boutons ne sont pas imprimes. */}
        <style>{"@media print { .no-print { display: none !important; } body { margin: 0 !important; } }"}</style>
      </head>
      <body style={{ fontFamily: "system-ui, sans-serif", maxWidth: 1100, margin: "40px auto", padding: "0 16px" }}>
        {children}
      </body>
    </html>
  );
}
