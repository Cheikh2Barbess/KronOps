// Le navigateur ne parle qu'a Next.js (meme domaine). Next.js relaie /api/* vers Django.
// Consequence : le cookie de session reste sur un seul domaine, sans CORS.
const API_URL = process.env.API_INTERNAL_URL || "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Django attend les URL avec "/" final : Next.js ne doit pas l'enlever.
  skipTrailingSlashRedirect: true,
  async rewrites() {
    return [
      // Avec "/" final (cas normal pour Django), puis sans.
      { source: "/api/:path*/", destination: `${API_URL}/api/:path*/` },
      { source: "/api/:path*", destination: `${API_URL}/api/:path*` },
    ];
  },
};

export default nextConfig;
