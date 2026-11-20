// SPDX-License-Identifier: Apache-2.0
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api";
import { AddDialog } from "./AddDialog";

vi.mock("../api", async (orig) => ({ ...(await orig<typeof import("../api")>()), addPatch: vi.fn() }));
const addPatch = vi.mocked(api.addPatch);
beforeEach(() => {
  addPatch.mockReset();
});

async function fill() {
  await userEvent.type(screen.getByLabelText("Name"), "my-fix");
  await userEvent.type(screen.getByLabelText("Message-ID or lore URL"), "https://lore.kernel.org/all/abc@x/");
  await userEvent.type(screen.getByLabelText("Links (one per line)"), "https://a.example/1{enter}https://b.example/2");
  await userEvent.type(screen.getByLabelText("Note"), "hello");
  await userEvent.click(screen.getByLabelText("someone else's thread"));
}

describe("AddDialog", () => {
  it("posts the fields and, on success, closes and opens the card", async () => {
    addPatch.mockResolvedValue({ name: "my-fix" } as Awaited<ReturnType<typeof api.addPatch>>);
    const onClose = vi.fn(), onAdded = vi.fn();
    render(<AddDialog onClose={onClose} onAdded={onAdded} />);
    await fill();
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(addPatch).toHaveBeenCalledWith({
      name: "my-fix", msgid: "https://lore.kernel.org/all/abc@x/", follow: true, note: "hello",
      links: ["https://a.example/1", "https://b.example/2"],
    });
    expect(onAdded).toHaveBeenCalledWith("my-fix");
    expect(onClose).toHaveBeenCalled();
  });

  it("omits empty optional fields", async () => {
    addPatch.mockResolvedValue({ name: "n" } as Awaited<ReturnType<typeof api.addPatch>>);
    render(<AddDialog onClose={() => {}} onAdded={() => {}} />);
    await userEvent.type(screen.getByLabelText("Name"), "n");
    await userEvent.type(screen.getByLabelText("Message-ID or lore URL"), "m@x");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(addPatch).toHaveBeenCalledWith({ name: "n", msgid: "m@x", follow: false });
  });

  it("shows the 409 message inline and stays open", async () => {
    addPatch.mockImplementation(async () => { throw new api.ApiError(409, "name belongs to another patch", null); });
    const onClose = vi.fn();
    render(<AddDialog onClose={onClose} onAdded={() => {}} />);
    await userEvent.type(screen.getByLabelText("Name"), "n");
    await userEvent.type(screen.getByLabelText("Message-ID or lore URL"), "m@x");
    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect((await screen.findByRole("alert")).textContent).toBe("name belongs to another patch");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes on Cancel", async () => {
    const onClose = vi.fn();
    render(<AddDialog onClose={onClose} onAdded={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
  });
});
