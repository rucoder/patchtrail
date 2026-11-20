// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { card } from "../fixtures";
import { columns, COLUMNS, TITLES } from "./board";

const NOW = 100 * 86400;
const day = (n: number) => NOW - n * 86400;
const col = (cs: ReturnType<typeof columns>, s: string) => cs.find((c) => c.stage === s)!;
const names = (l: { name: string }[]) => l.map((c) => c.name);

describe("columns", () => {
  it("has the six columns in order with titles", () => {
    expect(columns([], NOW).map((c) => c.stage)).toEqual([...COLUMNS]);
    expect(Object.values(TITLES)).toEqual(
      ["Submitted", "Reviewed", "Accepted", "Applied", "Released", "Backports"]);
  });

  it("assigns each card to its stage column", () => {
    const cs = columns([card("a", { stage: "reviewed" }), card("b", { stage: "released" }),
      card("c", { stage: "unknown" })], NOW);
    expect(names(col(cs, "reviewed").cards)).toEqual(["a"]);
    expect(names(col(cs, "released").cards)).toEqual(["b"]);
    expect(cs.flatMap((c) => c.cards).length).toBe(2);
  });

  it("orders unread first, then newest activity", () => {
    const cs = columns([
      card("old", { last_activity: 10 }), card("new", { last_activity: 30 }),
      card("unr", { unread: true, last_activity: 5 }),
    ], NOW);
    expect(names(col(cs, "submitted").cards)).toEqual(["unr", "new", "old"]);
  });

  it("folds finished cards after 30 days, not before", () => {
    const cs = columns([
      card("d29", { finished: true, finished_at: day(29) }),
      card("d31", { finished: true, finished_at: day(31) }),
      card("nf", { finished: false, finished_at: day(40) }),
    ], NOW);
    const c = col(cs, "submitted");
    expect(names(c.older)).toEqual(["d31"]);
    expect(names(c.cards).sort()).toEqual(["d29", "nf"]);
  });

  it("folds read idle cards; an unread idle card stays in view", () => {
    const cs = columns([
      card("idle", { idle: true }), card("unr", { idle: true, unread: true }), card("act"),
    ], NOW);
    const c = col(cs, "submitted");
    expect(names(c.idle)).toEqual(["idle"]);
    expect(names(c.cards).sort()).toEqual(["act", "unr"]);
  });

  it("never puts a card in both folds", () => {
    const cs = columns([card("x", { idle: true, finished: true, finished_at: day(60) })], NOW);
    const c = col(cs, "submitted");
    expect(names(c.older)).toEqual(["x"]);
    expect(c.idle).toEqual([]);
    expect(c.cards).toEqual([]);
  });
});
