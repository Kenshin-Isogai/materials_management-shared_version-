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


