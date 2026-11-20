// SPDX-License-Identifier: Apache-2.0
import { useCallback, useEffect, useMemo, useState } from "react";
import { act, getPatches, getStatus } from "./api";
import { AppContext, type AppState } from "./app-context";
import { TopBar } from "./components/TopBar";
import { defaultFilters, visible, type Filters } from "./lib/filters";
import { parseRoute, routePath, type Route } from "./lib/route";
import type { Card, Status } from "./types";

export const POLL_BUSY_MS = 2000; // while a fetch is running or starting
export const POLL_IDLE_MS = 30000;

export function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [patches, setPatches] = useState<Card[]>([]);
  const [filters, setFilters] = useState<Filters>(defaultFilters);
  const [route, setRoute] = useState<Route>(() => parseRoute(location.pathname));

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await getStatus());
    } catch {
      // keep the last status; the next poll tries again
    }
  }, []);
  const reloadPatches = useCallback(async () => {
    try {
      setPatches((await getPatches()).patches);
    } catch {
      // keep the last list
    }
  }, []);

  const busy = !!status?.running || !!status?.starting;
  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);
  useEffect(() => {
    const t = setInterval(() => void refreshStatus(), busy ? POLL_BUSY_MS : POLL_IDLE_MS);
    return () => clearInterval(t);
  }, [busy, refreshStatus]);

  // The list: every 30 s, and when a run finishes (last_run changes).
  const lastRunId = status?.last_run?.id ?? null;
  useEffect(() => {
    void reloadPatches();
  }, [reloadPatches, lastRunId]);
  useEffect(() => {
    const t = setInterval(() => void reloadPatches(), POLL_IDLE_MS);
    return () => clearInterval(t);
  }, [reloadPatches]);

  useEffect(() => {
    const onPop = () => setRoute(parseRoute(location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const navigate = useCallback((r: Route) => {
    history.pushState(null, "", routePath(r));
    setRoute(r);
  }, []);

  const runAction: AppState["runAction"] = useCallback(
    async (name, action, body) => {
      try {
        return await act(name, action, body);
      } finally {
        await reloadPatches();
      }
    },
    [reloadPatches],
  );

  const state: AppState = { status, patches, filters, route, navigate, reloadPatches, runAction };
  const shown = useMemo(() => visible(patches, filters), [patches, filters]);

  return (
    <AppContext.Provider value={state}>
      <div className="pt">
        <TopBar
          status={status}
          patches={patches}
          filters={filters}
          onFilters={setFilters}
          onStatus={setStatus}
          onRefresh={() => void refreshStatus()}
          onAdded={(name) => {
            void reloadPatches();
            navigate({ name, tab: "overview" });
          }}
        />
        {/* Tasks 10 to 12: the board, the detail panel and the thread view go here. */}
        <div className="pbody muted">
          {shown.length} patches{route.name ? ` · selected: ${route.name}` : ""}
        </div>
      </div>
    </AppContext.Provider>
  );
}
