// SPDX-License-Identifier: Apache-2.0
// What App shares with the board, the detail panel and the thread view (Tasks 10 to 12).
import { createContext, useContext } from "react";
import type { Filters } from "./lib/filters";
import type { Route } from "./lib/route";
import type { Action, Card, Status } from "./types";

export type AppState = {
  status: Status | null;
  patches: Card[]; // all of them, hidden and closed included
  filters: Filters;
  route: Route;
  clockOffset: number; // server clock minus the browser clock, seconds
  navigate: (r: Route) => void;
  reloadPatches: () => Promise<void>;
  /** Run an action on a patch, then re-fetch the patches. Throws ApiError. */
  runAction: (name: string, action: Action | "setNote", body?: Record<string, unknown>) => Promise<Card>;
};

export const AppContext = createContext<AppState | null>(null);

export function useApp(): AppState {
  const v = useContext(AppContext);
  if (!v) throw new Error("useApp outside AppContext");
  return v;
}
