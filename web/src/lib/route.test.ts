// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { parseRoute, routePath } from "./route";

describe("route", () => {
  it("parses the four shapes", () => {
    expect(parseRoute("/")).toEqual({ name: null, tab: "overview" });
    expect(parseRoute("/p/iowq-cpuset")).toEqual({ name: "iowq-cpuset", tab: "overview" });
    expect(parseRoute("/p/iowq-cpuset/thread")).toEqual({ name: "iowq-cpuset", tab: "thread" });
    expect(parseRoute("/p/iowq-cpuset/history")).toEqual({ name: "iowq-cpuset", tab: "history" });
  });
  it("round trips", () => {
    for (const p of ["/", "/p/a", "/p/a/thread", "/p/a/history"]) {
      expect(routePath(parseRoute(p))).toBe(p);
    }
  });
  it("gives name null for an unknown path", () => {
    expect(parseRoute("/nope/here").name).toBeNull();
    expect(parseRoute("/p/").name).toBeNull();
    expect(parseRoute("/p/a/zzz").name).toBeNull();
  });
  it("tolerates a trailing slash and encodes names", () => {
    expect(parseRoute("/p/a/").name).toBe("a");
    expect(routePath({ name: "a b", tab: "overview" })).toBe("/p/a%20b");
    expect(parseRoute("/p/a%20b").name).toBe("a b");
  });
});
