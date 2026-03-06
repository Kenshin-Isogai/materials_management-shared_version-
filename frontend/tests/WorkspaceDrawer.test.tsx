import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { WorkspaceDrawer } from "../src/components/WorkspaceDrawer";

describe("WorkspaceDrawer", () => {
  it("focuses the active panel and supports back navigation", async () => {
    const onClose = vi.fn();
    const onNavigate = vi.fn();
    const onBack = vi.fn();
    render(
      <WorkspaceDrawer
        breadcrumbs={[
          { key: "project:1", label: "Project 1" },
          { key: "item:2", label: "Item 2" },
        ]}
        onClose={onClose}
        onNavigate={onNavigate}
        onBack={onBack}
      >
        <div hidden aria-hidden="true">
          <button data-autofocus="true" type="button">
            Hidden Focus
          </button>
        </div>
        <div data-drawer-panel-active="true">
          <button data-autofocus="true" type="button">
            Active Focus
          </button>
        </div>
      </WorkspaceDrawer>,
    );

    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Active Focus" }));

    await userEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(onBack).toHaveBeenCalledTimes(1);

    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
