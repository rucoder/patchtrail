// SPDX-License-Identifier: Apache-2.0
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import type { Mail, MailGroup } from "../types";
import { Thread } from "./Thread";

vi.mock("../api", async (orig) => ({ ...(await orig<typeof import("../api")>()), getMails: vi.fn() }));
const getMails = vi.mocked(api.getMails);

const mail = (id: string, over: Partial<Mail> = {}): Mail => ({
  msgid: id, parent: null, depth: 0, date: 1000, from_name: `Who ${id}`, from_addr: `${id}@x`, you: false,
  subject: `subj ${id}`, new: false, body: `body of ${id}\n`, omitted: 0, lore_url: `https://lore/${id}`, ...over,
});
const show = (groups: MailGroup[], name = "p") => {
  getMails.mockResolvedValue({ groups });
  return render(<Thread name={name} tick={0} />);
};

beforeEach(() => getMails.mockReset());

describe("Thread", () => {
  it("indents by depth, 22px a level, capped at 6 levels", async () => {
    const { container } = show([{ label: null, mails: [mail("a", { depth: 0 }), mail("b", { depth: 2 }), mail("c", { depth: 9 })] }]);
    await screen.findAllByText(/Who a/);
    const m = [...container.querySelectorAll<HTMLElement>(".msg")];
    expect(m.map((e) => e.style.marginLeft)).toEqual(["0px", "44px", "132px"]);
  });

  it("opens new mails and collapses the others; clicking toggles", async () => {
    const { container } = show([{ label: null, mails: [mail("n", { new: true }), mail("o")] }]);
    const bodies = () => [...container.querySelectorAll("pre.mb")].map((e) => e.textContent);
    await screen.findByText(/body of n/);
    expect(container.querySelector(".msg.new")).toBeTruthy();
    expect(bodies()).toEqual(["body of n\n"]);
    await userEvent.click(screen.getByText(/Who o/));
    expect(bodies()).toEqual(["body of n\n", "body of o\n"]);
    await userEvent.click(screen.getByText(/Who o/));
    expect(bodies()).toEqual(["body of n\n"]);
  });

  it("Expand all / Collapse all", async () => {
    const { container } = show([{ label: null, mails: [mail("n", { new: true }), mail("o"), mail("q")] }]);
    await screen.findByText(/body of n/);
    const n = () => container.querySelectorAll("pre.mb").length;
    await userEvent.click(screen.getByRole("button", { name: "Expand all" }));
    expect(n()).toBe(3);
    await userEvent.click(screen.getByRole("button", { name: "Collapse all" }));
    expect(n()).toBe(0);
  });

  it("renders markup as text", async () => {
    const { container } = show([{ label: null, mails: [mail("n", { new: true, body: "hi <img src=x onerror=alert(1)>\n" })] }]);
    expect(await screen.findByText(/<img src=x onerror=alert\(1\)>/)).toBeTruthy();
    expect(container.querySelector("img")).toBeNull();
  });

  it("classes lines and expands a fold", async () => {
    const body = ["diff --git a/x b/x", ...Array.from({ length: 70 }, (_, i) => `+add${i}`), "> quoted", ""].join("\n");
    const { container } = show([{ label: null, mails: [mail("n", { new: true, body })] }]);
    const fold = await screen.findByRole("button", { name: "… 11 more lines" });
    expect(container.querySelector("pre.mb .dg")).toBeTruthy();
    expect(container.querySelector("pre.mb .q1")?.textContent).toBe("> quoted\n");
    expect(screen.queryByText("+add69")).toBeNull();
    await userEvent.click(fold);
    expect(screen.getByText("+add69")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /more lines/ })).toBeNull();
  });

  it("shows the omitted note, a lore link per mail, and backport groups after the series", async () => {
    show([
      { label: null, mails: [mail("a", { new: true, omitted: 2 })] },
      { label: "6.1.y backport", mails: [mail("b", { new: true })] },
    ]);
    expect(await screen.findByText("[2 non-text parts not shown]")).toBeTruthy();
    const links = screen.getAllByRole("link", { name: /lore/ });
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["https://lore/a", "https://lore/b"]);
    const text = document.body.textContent ?? "";
    expect(text.indexOf("6.1.y backport")).toBeGreaterThan(text.indexOf("body of a"));
    expect(text.indexOf("6.1.y backport")).toBeLessThan(text.indexOf("body of b"));
  });

  it("shows the neomutt command as text to select, without a clipboard (plain http)", async () => {
    vi.stubGlobal("navigator", { ...navigator, clipboard: undefined });
    show([{ label: null, mails: [mail("a")] }], "my-patch");
    const cmd = await screen.findByText("ptl open my-patch");
    expect(cmd.className).toContain("cmd");                  // user-select: all
    expect(screen.queryByRole("button", { name: "Copy" })).toBeNull();
    vi.unstubAllGlobals();
  });

  it("copies the neomutt command when there is a clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    show([{ label: null, mails: [mail("a")] }], "my-patch");
    await userEvent.click(await screen.findByRole("button", { name: "Copy" }));
    expect(writeText).toHaveBeenCalledWith("ptl open my-patch");
    expect(await screen.findByRole("button", { name: "Copied" })).toBeTruthy();
    vi.unstubAllGlobals();
  });

  it("only reads: no POST", async () => {
    const f = vi.fn();
    vi.stubGlobal("fetch", f);
    show([{ label: null, mails: [mail("n", { new: true })] }]);
    await screen.findByText(/body of n/);
    expect(f).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("shows a load error and an empty note", async () => {
    getMails.mockRejectedValue(new api.ApiError(404, "no such patch", null));
    render(<Thread name="p" tick={0} />);
    expect(await screen.findByRole("alert")).toBeTruthy();
    getMails.mockResolvedValue({ groups: [] });
    render(<Thread name="q" tick={0} />);
    await waitFor(() => expect(screen.getByText("No mails yet.")).toBeTruthy());
  });
});
