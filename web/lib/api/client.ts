/** Transport core: base-URL/key resolution, headers, and the fetch wrapper. */

import { ApiError } from "./types";
import type { ConnectionConfig } from "./types";

const DEFAULT_BASE_URL = "http://localhost:8000";

function envBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL || DEFAULT_BASE_URL;
}

function envApiKey(): string {
  return process.env.NEXT_PUBLIC_API_KEY || "";
}

export function resolveBaseUrl(config?: ConnectionConfig): string {
  const raw = (config?.baseUrl ?? envBaseUrl()).trim() || DEFAULT_BASE_URL;
  return raw.replace(/\/+$/, "");
}

export function resolveApiKey(config?: ConnectionConfig): string {
  return (config?.apiKey ?? envApiKey()).trim();
}

export function resolveOpenaiKey(config?: ConnectionConfig): string {
  return (config?.openaiKey ?? "").trim();
}

/**
 * Normalize a pasted API key. Users often copy a whole line from a `.env` file
 * or a shell export, e.g. `export OPENAI_API_KEY="sk-..."` — strip a leading
 * `export `, a `NAME=` assignment prefix, surrounding quotes, and whitespace so
 * only the key itself is kept. A bare key (`sk-...`, `sk-ant-...`) is returned
 * unchanged (it has no leading `identifier=`).
 */
export function normalizeApiKey(raw: string): string {
  let key = raw.trim().replace(/^export\s+/i, "");
  key = key.replace(/^[A-Za-z_][A-Za-z0-9_]*\s*=\s*/, "");
  return key.trim().replace(/^["']|["']$/g, "").trim();
}

export function buildHeaders(config?: ConnectionConfig, json = false): Headers {
  const headers = new Headers();
  if (json) {
    headers.set("Content-Type", "application/json");
  }
  const key = resolveApiKey(config);
  if (key) {
    headers.set("X-API-Key", key);
  }
  // Additive to the API key: when a user is logged in, also send the bearer JWT.
  const token = config?.token?.trim();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  // The visitor's own OpenAI key, when set: sent on every request so all LLM
  // calls (and upload) use their premium OpenAI model instead of the free one.
  const openaiKey = resolveOpenaiKey(config);
  if (openaiKey) {
    headers.set("X-OpenAI-Key", openaiKey);
  }
  return headers;
}

export async function readError(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: unknown };
    if (typeof data?.detail === "string") {
      return data.detail;
    }
    if (data?.detail != null) {
      return JSON.stringify(data.detail);
    }
  } catch {
    /* fall through to status text */
  }
  return response.statusText || `Request failed (${response.status})`;
}

export async function request<T>(
  path: string,
  init: RequestInit,
  config?: ConnectionConfig,
): Promise<T> {
  const url = `${resolveBaseUrl(config)}${path}`;
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new ApiError(
      "Could not reach the backend. Check that it is running and the base URL is correct.",
    );
  }
  if (!response.ok) {
    throw new ApiError(await readError(response), response.status);
  }
  return (await response.json()) as T;
}

/** Liveness probe. Returns true only when the backend reports `status: ok`. */
