// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { card } from "../fixtures";
import type { Card as CardT } from "../types";
import { Card } from "./Card";

const show = (c: CardT, sel = false, onSelect = () => {}) =>
  render(<Card card={c} selected={sel} onSelect={onSelect} />);

describe("Card", () => {
  it("shows the number of unread changes in the badge", () => {
    show(card("a", { unread: true, unread_changes: 3 }));
    expect(screen.getByText("3").className).toContain("badge");
  });
  it("shows 'new' when unread with no changes", () => {
    const { container } = show(card("a", { unread: true }));
    expect(screen.getByText("new").className).toContain("badge");
    expect(container.querySelector(".crd.u")).toBeTruthy();
  });
  it("shows no badge when read", () => {
    const { container } = show(card("a"));
    expect(container.querySelector(".badge")).toBeNull();
  });
  it("colours the chip per project, neutral for others", () => {
    const cls = (p: string) => {
      const { container, unmount } = show(card("a", { project: p }));
      const c = container.querySelector(".chip")!.className;
      unmount();
      return c;
    };
    expect(cls("kernel")).toContain(" k");
    expect(cls("qemu")).toContain(" q");
    expect(cls("grub")).toContain(" g");
    expect(cls("erofs-utils")).toContain(" e");
    expect(cls("liburing")).toContain(" l");
    expect(cls("other")).toBe("chip ");
  });
  it("shows your turn in red and the standing text", () => {
    show(card("a", { your_turn: true, standing: { kind: "x", who: "", since: 0, text: "2 days" } }));
    expect(screen.getByText("your turn").className).toContain("turn");
    expect(screen.getByText(/2 days/)).toBeTruthy();
  });
  it("shows the standing text without your turn", () => {
    show(card("a", { standing: { kind: "x", who: "", since: 0, text: "no reply" } }));
    expect(screen.queryByText("your turn")).toBeNull();
    expect(screen.getByText("no reply")).toBeTruthy();
  });
  it("tags following patches", () => {
    show(card("a", { relation: "following" }));
    expect(screen.getByText("following")).toBeTruthy();
  });
  it("renders the pills with their tone classes", () => {
    show(card("a", { pills: [
      { series: "6.18", state: "x", tone: "ok" }, { series: "6.6", state: "x", tone: "warn" },
      { series: "6.1", state: "x", tone: "bad" }, { series: "5.10", state: "x", tone: "na" },
    ] }));
    for (const [s, t] of [["6.18", "ok"], ["6.6", "warn"], ["6.1", "bad"], ["5.10", "na"]])
      expect(screen.getByText(s).className).toContain(`p-${t}`);
  });
  it("lists the link labels", () => {
    show(card("a", { links: [{ url: "u", label: "PR #1" }, { url: "v", label: "JIRA-2" }] }));
    expect(screen.getByText(/PR #1/)).toBeTruthy();
    expect(screen.getByText(/JIRA-2/)).toBeTruthy();
  });
  it("is selected by click and by keyboard, and marks sel", async () => {
    const onSelect = vi.fn();
    const { container } = show(card("a"), true, onSelect);
    expect(container.querySelector(".crd.sel")).toBeTruthy();
    await userEvent.click(screen.getByRole("button"));
    screen.getByRole("button").focus();
    await userEvent.keyboard("{Enter}");
    expect(onSelect).toHaveBeenCalledTimes(2);
    expect(onSelect).toHaveBeenCalledWith("a");
  });
});
