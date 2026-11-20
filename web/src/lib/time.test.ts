// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from "vitest";
import { clock, dayTime, elapsed, short } from "./time";

const t = new Date(2026, 10, 11, 16, 27, 5).getTime() / 1000; // local time

describe("time", () => {
  it("formats short, dayTime and clock in local time", () => {
    expect(short(t)).toBe("Nov 11");
    expect(dayTime(t)).toBe("2026-11-11 16:27");
    expect(clock(new Date(2026, 10, 11, 13, 2).getTime() / 1000)).toBe("13:02");
  });
  it("formats elapsed", () => {
    expect(elapsed(1000, 1000 + 252)).toBe("4m 12s");
    expect(elapsed(1000, 1000 + 65)).toBe("1m 05s");
    expect(elapsed(1000, 1000 + 9)).toBe("9s");
    expect(elapsed(1000, 1000 + 3725)).toBe("1h 02m");
    expect(elapsed(1000, 900)).toBe("0s");
  });
});
