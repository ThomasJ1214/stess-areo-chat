const session =
  typeof window === "undefined"
    ? null
    : new URLSearchParams(window.location.search).get("token");
export async function request<T = any>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (session) headers.set("X-Rocket-Session", session);
  if (init.body && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch(`/api${path}`, { ...init, headers });
  if (!response.ok) {
    let reason: string;
    try {
      const data = await response.json();
      reason =
        typeof data.detail === "string"
          ? data.detail
          : Array.isArray(data.detail)
            ? data.detail
                .map(
                  (item: any) =>
                    `${(item.loc || []).slice(1).join(".")}: ${item.msg}`,
                )
                .join("; ")
            : JSON.stringify(data.detail || data);
    } catch {
      reason = response.statusText;
    }
    throw new Error(reason || `Request failed (${response.status})`);
  }
  return response.json();
}
export function post<T = any>(path: string, value?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: value === undefined ? undefined : JSON.stringify(value),
  });
}
export function upload<T = any>(
  path: string,
  file: File,
  fields: Record<string, string> = {},
): Promise<T> {
  const data = new FormData();
  data.set("file", file);
  Object.entries(fields).forEach(([k, v]) => data.set(k, v));
  return request<T>(path, { method: "POST", body: data });
}
export async function download(path: string, filename: string) {
  const headers = new Headers();
  if (session) headers.set("X-Rocket-Session", session);
  const r = await fetch(`/api${path}`, { headers });
  if (!r.ok) throw new Error(await r.text());
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
