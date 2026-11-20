// SPDX-License-Identifier: Apache-2.0
import type {
  Action, AddBody, AddResult, Card, Detail, MailGroup, RunLogLine, Status,
} from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string, public body: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  if (method !== "GET") {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(body ?? {});
  }
  const res = await fetch(path, init);
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    // not JSON; the status still tells
  }
  if (!res.ok) {
    const msg = (data as { error?: unknown } | null)?.error;
    throw new ApiError(res.status, typeof msg === "string" ? msg : `HTTP ${res.status}`, data);
  }
  return data as T;
}

const enc = encodeURIComponent;

export const getStatus = () => call<Status>("GET", "/api/status");
export const fetchNow = () => call<Status>("POST", "/api/fetch", {});
export const getRunLog = (id: number, after: number) =>
  call<{ lines: RunLogLine[] }>("GET", `/api/runs/${id}/log?after=${after}`);
export const getPatches = () => call<{ patches: Card[] }>("GET", "/api/patches");
export const getPatch = (name: string) => call<Detail>("GET", `/api/patches/${enc(name)}`);
export const getMails = (name: string) =>
  call<{ groups: MailGroup[] }>("GET", `/api/patches/${enc(name)}/mails`);
export const addPatch = (body: AddBody) => call<AddResult>("POST", "/api/patches", body);

/** The POST actions of the contract, and `setNote` (PUT .../note). Answers the updated Card. */
export function act(
  name: string, action: Action | "setNote", body: Record<string, unknown> = {},
): Promise<Card> {
  const base = `/api/patches/${enc(name)}`;
  if (action === "setNote") return call<Card>("PUT", `${base}/note`, body);
  return call<Card>("POST", `${base}/${action}`, body);
}
