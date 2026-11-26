// Client API unique. Toutes les requetes passent par ici.
// Le cookie de session est HttpOnly : JavaScript ne le voit jamais, le navigateur l'envoie seul.

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

export class ApiError extends Error {
  constructor(public status: number, public body: unknown) {
    super(`Erreur API ${status}`);
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body) headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    if (!readCookie("csrftoken")) await fetch("/api/v1/auth/csrf/", { credentials: "same-origin" });
    headers.set("X-CSRFToken", readCookie("csrftoken") || "");
  }
  const response = await fetch(`/api/v1/${path}`, { ...options, headers, credentials: "same-origin" });
  const body = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, body);
  return body as T;
}
