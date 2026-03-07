import { useState } from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CatalogSearchResult } from "../src/lib/types";

const apiGetMock = vi.fn().mockResolvedValue({ query: "", results: [] });

vi.mock("../src/lib/api", () => ({
  apiGet: (...args: unknown[]) => apiGetMock(...args),
}));

import { CatalogPicker } from "../src/components/CatalogPicker";

const firstItem: CatalogSearchResult = {
  entity_type: "item",
  entity_id: 1,
  value_text: "ITEM-001",
  display_label: "ITEM-001 #1",
  summary: "Lens",
  match_source: "item_number",
};

function CatalogPickerHost() {
  const [value, setValue] = useState<CatalogSearchResult | null>(null);

  return (
    <div>
      <CatalogPicker
        allowedTypes={["item"]}
        onChange={setValue}
        recentKey="catalog-picker-test"
        value={value}
      />
      <button onClick={() => setValue(firstItem)} type="button">
        Select First
      </button>
      <button onClick={() => setValue(null)} type="button">
        Clear External
      </button>
    </div>
  );
}

describe("CatalogPicker", () => {
  beforeEach(() => {
    apiGetMock.mockClear();
    window.localStorage.clear();
  });

  afterEach(() => {
    cleanup();
  });

  it("syncs external single-value updates while the picker is open", async () => {
    const user = userEvent.setup();
    render(<CatalogPickerHost />);

    const input = screen.getByRole("textbox");
    await user.click(input);
    expect((input as HTMLInputElement).value).toBe("");

    await user.click(screen.getByRole("button", { name: "Select First" }));
    await waitFor(() => {
      expect((input as HTMLInputElement).value).toBe("ITEM-001 #1");
    });

    await user.click(screen.getByRole("button", { name: "Clear External" }));
    await waitFor(() => {
      expect((input as HTMLInputElement).value).toBe("");
    });
  });

  it("keeps Escape on picker controls from bubbling to parent handlers", async () => {
    const user = userEvent.setup();
    const parentKeyDown = vi.fn();

    render(
      <div onKeyDown={parentKeyDown}>
        <CatalogPickerHost />
      </div>,
    );

    await user.click(screen.getByRole("button", { name: "Select First" }));
    const input = screen.getByRole("textbox");
    await user.click(input);
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Clear" }));
    parentKeyDown.mockClear();

    await user.keyboard("{Escape}");

    expect(parentKeyDown).not.toHaveBeenCalled();
    expect((input as HTMLInputElement).value).toBe("ITEM-001 #1");
  });
});
