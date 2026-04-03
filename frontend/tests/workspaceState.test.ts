import { describe, expect, it } from "vitest";

import {
  nextSynchronizedBoardDate,
} from "../src/lib/workspaceState";

describe("workspaceState", () => {
  it("syncs the board date to the refreshed effective analysis date when local preview is clean", () => {
    const nextDate = nextSynchronizedBoardDate({
      analysisDateDraft: "",
      analysisDateApplied: "",
      projectPlannedStart: null,
      analysisTargetDate: "2026-03-07",
    });

    expect(nextDate).toBe("2026-03-07");
  });

  it("preserves local preview edits when the date input is dirty", () => {
    const nextDate = nextSynchronizedBoardDate({
      analysisDateDraft: "2026-03-10",
      analysisDateApplied: "2026-03-07",
      projectPlannedStart: "2026-03-07",
      analysisTargetDate: "2026-03-07",
    });

    expect(nextDate).toBeNull();
  });
});
