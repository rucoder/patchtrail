// SPDX-License-Identifier: Apache-2.0
import type { Action } from "../types";

/** Runs an action on the open patch. Answers false after showing the error, so a form keeps its input. */
export type ActFn = (action: Action | "setNote", body?: Record<string, unknown>) => Promise<boolean>;

const KEY = "patchtrail.panelHeight";
export const PANEL_DEFAULT = 340;
export const PANEL_MIN = 120;

export function clampPanel(h: number, viewport: number): number {
  return Math.round(Math.max(PANEL_MIN, Math.min(h, Math.max(PANEL_MIN, viewport - 200))));
}

export function loadPanelHeight(): number {
  try {
    const n = Number(localStorage.getItem(KEY));
    return Number.isFinite(n) && n >= PANEL_MIN ? n : PANEL_DEFAULT;
  } catch {
    return PANEL_DEFAULT;
  }
}

export function savePanelHeight(h: number): void {
  try {
    localStorage.setItem(KEY, String(h));
  } catch {
    // storage unavailable: the height is just not remembered
  }
}
