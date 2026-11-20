// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { detail } from "../fixtures";
import { dayTime } from "../lib/time";
import { History } from "./History";

describe("History", () => {
  it("lists every entry in the order given with time and texts, bold when flagging", () => {
    const d = detail("p", { history: [
      { at: 1_700_000_200, changes: [{ field: "stage", text: "stage: a to b", flags: true }, { field: "m", text: "mail: +1", flags: false }] },
      { at: 1_700_000_100, changes: [{ field: "f", text: "found on lore", flags: false }] },
      { at: 1_700_000_000, changes: [{ field: "x", text: "older", flags: false }] },
      { at: 1_699_999_900, changes: [{ field: "x", text: "oldest", flags: false }] },
      { at: 1_699_999_800, changes: [{ field: "x", text: "sixth", flags: false }] },
      { at: 1_699_999_700, changes: [{ field: "x", text: "seventh", flags: false }] },
    ] });
    const { container } = render(<History d={d} />);
    expect(screen.getByText(dayTime(1_700_000_200))).toBeTruthy();
    expect(screen.getByText("seventh")).toBeTruthy();
    expect(screen.getByText("stage: a to b").tagName).toBe("B");
    expect(screen.getByText("mail: +1").tagName).not.toBe("B");
    const text = container.textContent!;
    expect(text.indexOf("stage: a to b")).toBeLessThan(text.indexOf("found on lore"));
  });

  it("says so when empty", () => {
    render(<History d={detail("p")} />);
    expect(screen.getByText("No history yet.")).toBeTruthy();
  });
});
