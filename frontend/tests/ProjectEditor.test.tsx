import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SWRConfig } from "swr";

const apiGetMock = vi.fn();
const apiGetWithPaginationMock = vi.fn();
const apiSendMock = vi.fn();
const apiDownloadMock = vi.fn();

vi.mock("../src/lib/api", () => ({
  apiDownload: (...args: unknown[]) => apiDownloadMock(...args),
  apiGet: (...args: unknown[]) => apiGetMock(...args),
  apiGetWithPagination: (...args: unknown[]) => apiGetWithPaginationMock(...args),
  apiSend: (...args: unknown[]) => apiSendMock(...args),
}));

vi.mock("../src/components/CatalogPicker", () => ({
  CatalogPicker: () => <div>Catalog Picker</div>,
}));

import { ProjectEditor } from "../src/components/ProjectEditor";

function renderEditor() {
  render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <ProjectEditor active />
    </SWRConfig>,
  );
}

describe("ProjectEditor", () => {
  beforeEach(() => {
    apiGetMock.mockReset();
    apiGetWithPaginationMock.mockReset();
    apiSendMock.mockReset();
    apiDownloadMock.mockReset();
    apiGetWithPaginationMock.mockResolvedValue({ data: [], pagination: undefined });
  });

  it("downloads unresolved preview rows as an Items import CSV", async () => {
    apiSendMock.mockResolvedValue({
      summary: {
        total_rows: 1,
        exact: 0,
        high_confidence: 0,
        needs_review: 0,
        unresolved: 1,
      },
      can_auto_accept: false,
      rows: [
        {
          row: 1,
          raw_line: "PROJECT-MISSING-001,2",
          raw_target: "PROJECT-MISSING-001",
          quantity: "2",
          quantity_raw: "2",
          quantity_defaulted: false,
          status: "unresolved",
          message: "No registered item matched this line.",
          requires_user_selection: true,
          allowed_entity_types: ["item"],
          suggested_match: null,
          candidates: [],
        },
      ],
    });
    apiDownloadMock.mockResolvedValue(undefined);

    renderEditor();

    fireEvent.change(screen.getByPlaceholderText(/LAS-001,2[\s\S]*MIRROR-19,4/), {
      target: { value: "PROJECT-MISSING-001,2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Preview Parse" }));

    await waitFor(() => {
      expect(apiSendMock).toHaveBeenCalledWith("/projects/requirements/preview", {
        method: "POST",
        body: JSON.stringify({ text: "PROJECT-MISSING-001,2" }),
      });
    });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Download Unresolved Items CSV" })).toBeTruthy();
    });
    fireEvent.click(screen.getByRole("button", { name: "Download Unresolved Items CSV" }));

    await waitFor(() => {
      expect(apiDownloadMock).toHaveBeenCalledWith(
        "/projects/requirements/preview/unresolved-items.csv",
        "project_requirements_unresolved_items_import.csv",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            rows: [
              {
                raw_target: "PROJECT-MISSING-001",
                status: "unresolved",
              },
            ],
            text: "PROJECT-MISSING-001,2",
          }),
        },
      );
    });
  });
});
