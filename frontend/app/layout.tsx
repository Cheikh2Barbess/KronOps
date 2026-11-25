import type { ReactNode } from "react";

export const metadata = { title: "KronOps" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="fr">
      <body style={{ fontFamily: "system-ui, sans-serif", maxWidth: 640, margin: "40px auto", padding: "0 16px" }}>
        {children}
      </body>
    </html>
  );
}
