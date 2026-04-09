import { describe, expect, it } from "vitest";

import {
  derivePlanningBoardDate,
  getExplicitBoardTargetDate,
  nextSynchronizedBoardDate,
  todayJstDateString,
} from "../src/lib/workspaceState";

describe("workspaceState", () => {
  it("formats today's date in JST", () => {
    const today = todayJstDateString(new Date("2026-04-07T00:30:00.000Z"));

    expect(today).toBe("2026-04-07");
  });

  it("delays a past planned start to today for board analysis", () => {
    const nextDate = derivePlanningBoardDate({
      projectPlannedStart: "2026-04-01",
      today: "2026-04-07",
    });

    expect(nextDate).toBe("2026-04-07");
  });

  it("keeps a future planned start unchanged for board analysis", () => {
    const nextDate = derivePlanningBoardDate({
      projectPlannedStart: "2026-04-09",
      today: "2026-04-07",
    });

    expect(nextDate).toBe("2026-04-09");
  });

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

  it("sends today as an explicit override when the project is already delayed", () => {
    const targetDate = getExplicitBoardTargetDate({
      analysisDateApplied: "2026-04-07",
      projectPlannedStart: "2026-04-01",
      today: "2026-04-07",
    });

    expect(targetDate).toBe("2026-04-07");
  });

  it("sends an explicit override when the user chooses a later board date", () => {
    const targetDate = getExplicitBoardTargetDate({
      analysisDateApplied: "2026-04-10",
      projectPlannedStart: "2026-04-01",
      today: "2026-04-07",
    });

    expect(targetDate).toBe("2026-04-10");
  });

  it("does not send an explicit override when an unscheduled project uses today's default board date", () => {
    const targetDate = getExplicitBoardTargetDate({
      analysisDateApplied: "2026-04-07",
      projectPlannedStart: null,
      today: "2026-04-07",
    });

    expect(targetDate).toBeNull();
  });
});
