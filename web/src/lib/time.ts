// SPDX-License-Identifier: Apache-2.0
// Times arrive as epoch seconds and are shown in local time.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const p2 = (n: number) => String(n).padStart(2, "0");

export const short = (t: number): string => {
  const d = new Date(t * 1000);
  return `${MONTHS[d.getMonth()]} ${d.getDate()}`;
};

export const clock = (t: number): string => {
  const d = new Date(t * 1000);
  return `${p2(d.getHours())}:${p2(d.getMinutes())}`;
};

export const dayTime = (t: number): string => {
  const d = new Date(t * 1000);
  return `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${clock(t)}`;
};

export function elapsed(from: number, now: number): string {
  const s = Math.max(0, Math.floor(now - from));
  if (s >= 3600) return `${Math.floor(s / 3600)}h ${p2(Math.floor((s % 3600) / 60))}m`;
  if (s >= 60) return `${Math.floor(s / 60)}m ${p2(s % 60)}s`;
  return `${s}s`;
}
