import { getLocale } from "@/i18n/translations";
import { apiErrorDetail } from "./validators/error";

class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

// Without a parser a helper returns `unknown`: a response is only typed after it is validated.
type ApiParser<T> = (raw: unknown) => T;
type TextWithMetaResponse = { body: string; headers: Headers };

function applyParser<T>(value: unknown, parser: ApiParser<T>): T;
function applyParser(value: unknown): unknown;
function applyParser<T>(value: unknown, parser?: ApiParser<T>) {
  return parser ? parser(value) : value;
}

async function request(path: string, options: RequestInit & { responseType?: string } = {}): Promise<unknown> {
  const { responseType, ...fetchOptions } = options;
  const headers = new Headers(fetchOptions.headers as HeadersInit | undefined);
  headers.set("Accept-Language", getLocale());
  const response = await fetch(path, { ...fetchOptions, headers });
  const contentType = response.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    if (isJson) {
      try {
        const body = await response.json();
        detail = apiErrorDetail(body, response.status);
      } catch {
        // keep default
      }
    }
    throw new ApiError(response.status, typeof detail === "string" ? detail : String(detail));
  }

  if (responseType === "text") {
    return response.text();
  }
  if (responseType === "text-with-meta") {
    const text = await response.text();
    return { body: text, headers: response.headers } satisfies TextWithMetaResponse;
  }
  if (isJson) {
    return response.json();
  }
  return response.text();
}

function jsonHeaders(): Record<string, string> {
  return {
    Accept: "application/json",
    "Content-Type": "application/json",
  };
}

type QueryPrimitive = string | number | boolean | null | undefined;
type QueryValue = QueryPrimitive | QueryPrimitive[];

export function buildQuery(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === null || value === undefined || value === "") {
      return;
    }
    const values = Array.isArray(value) ? value : [value];
    values.forEach((entry) => {
      if (entry === null || entry === undefined || entry === "") {
        return;
      }
      search.append(key, String(entry));
    });
  });
  const query = search.toString();
  return query ? `?${query}` : "";
}

export function withQuery(path: string, params: Record<string, QueryValue>): string {
  const query = buildQuery(params);
  return query ? `${path}${query}` : path;
}

export function apiGet<T>(path: string, parser: ApiParser<T>): Promise<T>;
export async function apiGet<T>(path: string, parser: ApiParser<T>) {
  return parser(await request(path));
}

export function apiPost<T>(path: string, body: unknown, parser: ApiParser<T>): Promise<T>;
export function apiPost(path: string, body?: unknown): Promise<unknown>;
export async function apiPost<T>(path: string, body?: unknown, parser?: ApiParser<T>) {
  const raw = await request(path, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(body ?? {}),
  });
  return parser ? applyParser(raw, parser) : applyParser(raw);
}

export function apiPut<T>(path: string, body: unknown, parser: ApiParser<T>): Promise<T>;
export function apiPut(path: string, body?: unknown): Promise<unknown>;
export async function apiPut<T>(path: string, body?: unknown, parser?: ApiParser<T>) {
  const raw = await request(path, {
    method: "PUT",
    headers: jsonHeaders(),
    body: JSON.stringify(body ?? {}),
  });
  return parser ? applyParser(raw, parser) : applyParser(raw);
}

export function apiDelete<T>(path: string, parser: ApiParser<T>): Promise<T>;
export function apiDelete(path: string): Promise<unknown>;
export async function apiDelete<T>(path: string, parser?: ApiParser<T>) {
  const raw = await request(path, { method: "DELETE" });
  return parser ? applyParser(raw, parser) : applyParser(raw);
}

export function apiUpload<T>(path: string, file: File, fields: Record<string, string>, parser: ApiParser<T>): Promise<T>;
export function apiUpload(path: string, file: File, fields?: Record<string, string>): Promise<unknown>;
export async function apiUpload<T>(
  path: string,
  file: File,
  fields: Record<string, string> = {},
  parser?: ApiParser<T>,
) {
  const formData = new FormData();
  formData.append("file", file);
  Object.entries(fields).forEach(([key, value]) => {
    formData.append(key, value ?? "");
  });
  const raw = await request(path, { method: "POST", body: formData });
  return parser ? applyParser(raw, parser) : applyParser(raw);
}

export async function apiGetText(path: string): Promise<{ body: string; headers: Headers }> {
  const raw = await request(path, { responseType: "text-with-meta" });
  if (
    typeof raw === "object" &&
    raw !== null &&
    "body" in raw &&
    "headers" in raw &&
    typeof raw.body === "string" &&
    raw.headers instanceof Headers
  ) {
    return {
      body: raw.body,
      headers: raw.headers,
    };
  }
  throw new ApiError(500, "Expected text-with-meta response");
}

export { ApiError };
