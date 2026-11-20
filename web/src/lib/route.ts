// SPDX-License-Identifier: Apache-2.0
export type Tab = "overview" | "thread" | "history";
export type Route = { name: string | null; tab: Tab };

export function parseRoute(pathname: string): Route {
  const none: Route = { name: null, tab: "overview" };
  const segs = pathname.replace(/^\/+|\/+$/g, "").split("/");
  if (segs.length === 1 && segs[0] === "") return none;
  if (segs[0] !== "p" || segs.length < 2 || segs.length > 3 || segs[1] === "") return none;
  let name: string;
  try {
    name = decodeURIComponent(segs[1]);
  } catch {
    return none;
  }
  if (segs.length === 2) return { name, tab: "overview" };
  if (segs[2] === "thread" || segs[2] === "history") return { name, tab: segs[2] };
  return none;
}

export function routePath(r: Route): string {
  if (r.name === null) return "/";
  const base = `/p/${encodeURIComponent(r.name)}`;
  return r.tab === "overview" ? base : `${base}/${r.tab}`;
}
