import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it } from "vitest";

import { CommandPalette } from "@/components/CommandPalette";

beforeAll(() => {
  class ResizeObserverMock {
    observe() {}
    unobserve() {}
    disconnect() {}
  }

  Object.defineProperty(window, "ResizeObserver", {
    writable: true,
    value: ResizeObserverMock,
  });

  Object.defineProperty(Element.prototype, "scrollIntoView", {
    writable: true,
    value: () => {},
  });
});

describe("CommandPalette", () => {
  it("opens from Ctrl+K without crashing", () => {
    render(
      <MemoryRouter>
        <CommandPalette />
      </MemoryRouter>,
    );

    fireEvent.keyDown(document, { key: "k", ctrlKey: true });

    expect(screen.getByPlaceholderText("Type to search pages...")).toBeTruthy();
    expect(screen.getByText("Dashboard")).toBeTruthy();
  });
});
