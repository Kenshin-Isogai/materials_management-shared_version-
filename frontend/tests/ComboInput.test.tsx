import { useState } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { ComboInput } from "../src/components/ComboInput";

function ComboInputHost() {
  const [value, setValue] = useState("");

  return (
    <ComboInput
      value={value}
      onChange={setValue}
      options={["Thorlabs", "Edmund Optics", "Sigma Koki"]}
      placeholder="Manufacturer"
    />
  );
}

describe("ComboInput", () => {
  afterEach(() => {
    cleanup();
  });

  it("supports keyboard navigation and selection", async () => {
    const user = userEvent.setup();
    render(<ComboInputHost />);

    const input = screen.getByRole("combobox");
    await user.click(input);
    await user.keyboard("{ArrowDown}{Enter}");

    expect((input as HTMLInputElement).value).toBe("Edmund Optics");
  });

  it("exposes combobox and listbox accessibility semantics", async () => {
    const user = userEvent.setup();
    render(<ComboInputHost />);

    const input = screen.getByRole("combobox");
    expect(input.getAttribute("aria-expanded")).toBe("false");

    await user.click(input);

    expect(input.getAttribute("aria-expanded")).toBe("true");
    expect(input.getAttribute("aria-autocomplete")).toBe("list");
    expect(screen.getByRole("listbox")).not.toBeNull();

    await user.keyboard("{ArrowDown}");

    const activeId = input.getAttribute("aria-activedescendant");
    expect(activeId).toBeTruthy();
    const activeOption = screen.getByRole("option", { name: "Edmund Optics" });
    expect(activeOption.getAttribute("aria-selected")).toBe("true");
    expect(document.getElementById(activeId ?? "")).toBe(activeOption);
  });
});
