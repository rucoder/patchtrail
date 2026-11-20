// SPDX-License-Identifier: Apache-2.0
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { act, getPatches, getStatus } from "./api";
import { AppContext, type AppState } from "./app-context";
import { Board } from "./components/Board";
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

  const [clockOffset, setClockOffset] = useState(0); // server clock minus ours, seconds
  const [connError, setConnError] = useState<string | null>(null);
  const issued = useRef(0); // sequence of status requests and fresh statuses
  const applied = useRef(0); // newest sequence applied so far

  const applyStatus = useCallback((s: Status, seq: number) => {
    if (seq <= applied.current) return; // a stale reply must not overwrite a newer one
    applied.current = seq;
    setStatus(s);
    setClockOffset(s.now - Date.now() / 1000);
  }, []);
  const refreshStatus = useCallback(async () => {
    const seq = ++issued.current;
    try {
      applyStatus(await getStatus(), seq);
      setConnError(null);
    } catch (e) {
      // keep the last status; the next poll retries
      setConnError(e instanceof Error ? e.message : String(e));
    }
  }, [applyStatus]);
  const onStatus = useCallback((s: Status) => applyStatus(s, ++issued.current), [applyStatus]);
  const reloadPatches = useCallback(async () => {
    try {
      setPatches((await getPatches()).patches);
      setConnError(null);
    } catch (e) {
      setConnError(e instanceof Error ? e.message : String(e));
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

  const state: AppState = useMemo(
    () => ({ status, patches, filters, route, navigate, reloadPatches, runAction, clockOffset }),
    [status, patches, filters, route, navigate, reloadPatches, runAction, clockOffset],
  );
  const shown = useMemo(() => visible(patches, filters), [patches, filters]);

  return (
    <AppContext.Provider value={state}>
      <div className="pt">
        <TopBar
          status={status}
          patches={patches}
          filters={filters}
          onFilters={setFilters}
          onStatus={onStatus}
          connError={connError}
          clockOffset={clockOffset}
          onRefresh={() => void refreshStatus()}
          onAdded={(name) => {
            void reloadPatches();
            navigate({ name, tab: "overview" });
          }}
        />
        <Board cards={shown} />
        {/* Tasks 11 and 12: the detail panel and the thread view go here. */}
      </div>
    </AppContext.Provider>
  );
}
