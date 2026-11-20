// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { card } from "../fixtures";
import { defaultFilters, visible, type Filters } from "./filters";

const cards = [
  card("open-k", { unread: true }),
  card("open-q", { project: "qemu", your_turn: true }),
  card("hid", { hidden: true }),
  card("hid-closed", { hidden: true, closed: "dropped" }),
  card("closed", { closed: "rejected" }),
];
const f = (o: Partial<Filters>): Filters => ({ ...defaultFilters, ...o });
const names = (o: Partial<Filters>) => visible(cards, f(o)).map((c) => c.name);

describe("visible", () => {
  it("open: not hidden and not closed", () => {
    expect(names({})).toEqual(["open-k", "open-q"]);
  });
  it("hidden: hidden ones that are not closed", () => {
    expect(names({ view: "hidden" })).toEqual(["hid"]);
  });
  it("closed: closed ones, hidden or not", () => {
    expect(names({ view: "closed" })).toEqual(["hid-closed", "closed"]);
  });
  it("filters by project", () => {
    expect(names({ project: "qemu" })).toEqual(["open-q"]);
  });
  it("unread only", () => {
    expect(names({ unread: true })).toEqual(["open-k"]);
  });
  it("your turn", () => {
    expect(names({ turn: true })).toEqual(["open-q"]);
  });
  it("combines project and toggles", () => {
    expect(names({ project: "kernel", turn: true })).toEqual([]);
    expect(names({ project: "kernel", unread: true })).toEqual(["open-k"]);
  });
});
