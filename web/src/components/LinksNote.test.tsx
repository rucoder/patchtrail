// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { card } from "../fixtures";
import type { Card } from "../types";
import { LinksNote } from "./LinksNote";

const act = vi.fn(async () => true);
function show(over: Partial<Card> = {}) {
  act.mockClear();
  return render(<LinksNote card={card("p", over)} act={act} />);
}

describe("LinksNote", () => {
  it("adds a link", async () => {
    show();
    await userEvent.type(screen.getByLabelText("Add link"), "https://example.com/pr/1");
    await userEvent.click(screen.getByText("Add"));
    expect(act).toHaveBeenCalledWith("links", { add: ["https://example.com/pr/1"] });
  });

  it("removes a link by its url", async () => {
    show({ links: [{ url: "https://example.com/pr/1", label: "PR 1" }] });
    expect(screen.getByText("PR 1").getAttribute("href")).toBe("https://example.com/pr/1");
    await userEvent.click(screen.getByLabelText("Remove PR 1"));
    expect(act).toHaveBeenCalledWith("links", { remove: ["https://example.com/pr/1"] });
  });

  it("edits the note", async () => {
    show({ note: "old" });
    await userEvent.click(screen.getByText("old"));
    const box = screen.getByLabelText("Note");
    await userEvent.clear(box);
    await userEvent.type(box, "new note{Enter}");
    expect(act).toHaveBeenCalledWith("setNote", { note: "new note" });
  });

  it("clears the note when emptied", async () => {
    show({ note: "old" });
    await userEvent.click(screen.getByText("old"));
    await userEvent.clear(screen.getByLabelText("Note"));
    await userEvent.click(screen.getByText("Save"));
    expect(act).toHaveBeenCalledWith("setNote", { note: null });
  });

  it("cancels the edit with Esc without saving", async () => {
    show({ note: "old" });
    await userEvent.click(screen.getByText("old"));
    await userEvent.type(screen.getByLabelText("Note"), "x{Escape}");
    expect(act).not.toHaveBeenCalled();
    expect(screen.getByText("old")).toBeTruthy();
  });
});
