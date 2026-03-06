export function nextSynchronizedBoardDate(_props: {
  analysisDateDraft: string;
  analysisDateApplied: string;
  projectPlannedStart: string | null | undefined;
  analysisTargetDate: string | null;
}): string | null {
  const { analysisDateDraft, analysisDateApplied, projectPlannedStart, analysisTargetDate } = _props;
  if (analysisDateDraft.trim() !== analysisDateApplied.trim()) return null;
  if (analysisTargetDate == null) return null;
  const nextBoardDate = analysisTargetDate;
  if (analysisDateApplied.trim() === nextBoardDate) return null;
  return nextBoardDate;
}

export function resolveDrawerStackPush<T extends { key: string }>(
  current: T[],
  context: T,
): {
  nextStack: T[];
  discardedKeys: string[];
} {
  const existingIndex = current.findIndex((entry) => entry.key === context.key);
  if (existingIndex >= 0) {
    return {
      nextStack: current.slice(0, existingIndex + 1),
      discardedKeys: current.slice(existingIndex + 1).map((entry) => entry.key),
    };
  }
  return {
    nextStack: [...current, context],
    discardedKeys: [],
  };
}
