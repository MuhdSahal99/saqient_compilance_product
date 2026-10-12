/** Single place for HTTP. Adds credentials + CSRF header, normalises errors. */

let csrfToken = "";

export function setCsrfToken(token: string) {
  csrfToken = token;
}

export class ApiError extends Error {
  status: number;
  data: Record<string, unknown>;
  constructor(status: number, message: string, data: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

const UNSAFE = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const method = (init.method ?? (init.json !== undefined ? "POST" : "GET")).toUpperCase();
  const headers = new Headers(init.headers);
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  if (UNSAFE.has(method) && csrfToken) headers.set("X-CSRF-Token", csrfToken);
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { ...init, method, headers, body, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "The server could not be reached. Check your connection and try again.");
  }
  if (res.status === 204) return undefined as T;
  const isJson = res.headers.get("content-type")?.includes("application/json");
  const data = isJson ? await res.json().catch(() => ({})) : {};
  if (!res.ok) {
    const detail = typeof data.detail === "string" ? data.detail : `Request failed (${res.status}).`;
    throw new ApiError(res.status, detail, data);
  }
  return data as T;
}

/** Upload with progress (fetch has no upload progress events). */
export function uploadWithProgress<T>(
  path: string,
  form: FormData,
  onProgress: (fraction: number) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api${path}`);
    xhr.withCredentials = true;
    if (csrfToken) xhr.setRequestHeader("X-CSRF-Token", csrfToken);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      let data: Record<string, unknown> = {};
      try {
        data = JSON.parse(xhr.responseText || "{}");
      } catch {
        /* non-JSON error page */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as T);
      else
        reject(
          new ApiError(xhr.status, typeof data.detail === "string" ? data.detail : `Upload failed (${xhr.status}).`, data),
        );
    };
    xhr.onerror = () => reject(new ApiError(0, "The upload was interrupted. Check your connection and retry."));
    xhr.send(form);
  });
}

export function qs(params: Record<string, string | number | boolean | undefined | null | string[]>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "" || v === false) continue;
    if (Array.isArray(v)) v.forEach((x) => sp.append(k, x));
    else sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}
