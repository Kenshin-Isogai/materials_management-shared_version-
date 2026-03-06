import { describe, expect, it } from "vitest";

import {
  nextSynchronizedBoardDate,
  resolveDrawerStackPush,
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

  it("reports discarded drawer keys when reopening an earlier stack entry", () => {
    const resolved = resolveDrawerStackPush(
      [
        { key: "project:1" },
        { key: "item:2" },
        { key: "rfq:1:2" },
      ],
      { key: "project:1" },
    );

    expect(resolved.nextStack.map((entry) => entry.key)).toEqual(["project:1"]);
    expect(resolved.discardedKeys).toEqual(["item:2", "rfq:1:2"]);
  });
});
