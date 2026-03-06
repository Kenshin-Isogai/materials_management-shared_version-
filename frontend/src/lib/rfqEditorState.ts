import {
  areRfqLineDraftsEqual,
  createRfqLineDraft,
  type RfqLineDraft,
} from "./editorDrafts";
import type { RfqBatchDetail, RfqBatchStatus, RfqLine } from "./types";

export type RfqBatchBaseline = {
  title: string;
  status: RfqBatchStatus;
  note: string;
};

export function buildLineDraftMap(lines: RfqLine[]): Record<number, RfqLineDraft> {
  return Object.fromEntries(lines.map((line) => [line.line_id, createRfqLineDraft(line)]));
}

export function createRfqBatchBaseline(detail: Pick<RfqBatchDetail, "title" | "status" | "note">): RfqBatchBaseline {
  return {
    title: detail.title,
    status: detail.status,
    note: detail.note ?? "",
  };
}

export function orderVisibleRfqLines(lines: RfqLine[], highlightedItemId: number | null): RfqLine[] {
  if (!highlightedItemId) return lines;
  const matching = lines.filter((line) => line.item_id === highlightedItemId);
  if (!matching.length) return lines;
  return [...matching, ...lines.filter((line) => line.item_id !== highlightedItemId)];
}

export function mergeRehydratedLineDrafts(
  currentDrafts: Record<number, RfqLineDraft>,
  currentBaseline: Record<number, RfqLineDraft>,
  serverDrafts: Record<number, RfqLineDraft>,
  pendingLineIds: number[],
): {
  drafts: Record<number, RfqLineDraft>;
  baseline: Record<number, RfqLineDraft>;
} {
  const pendingIds = new Set(pendingLineIds);
  const nextDrafts = { ...currentDrafts };
  const nextBaseline = { ...currentBaseline };

  for (const lineId of pendingIds) {
    const serverDraft = serverDrafts[lineId];
    if (!serverDraft) continue;
    if (!areRfqLineDraftsEqual(nextDrafts[lineId], serverDraft)) {
      nextDrafts[lineId] = serverDraft;
    }
    if (!areRfqLineDraftsEqual(nextBaseline[lineId], serverDraft)) {
      nextBaseline[lineId] = serverDraft;
    }
  }

  return {
    drafts: nextDrafts,
    baseline: nextBaseline,
  };
}
