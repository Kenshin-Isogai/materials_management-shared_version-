function normalizeBoardDate(value: string | null | undefined): string {
  return (value ?? "").trim();
}

export function todayJstDateString(now: Date = new Date()): string {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
  return formatter.format(now);
}

export function derivePlanningBoardDate(_props: {
  projectPlannedStart: string | null | undefined;
  today?: string;
}): string {
  const projectPlannedStart = normalizeBoardDate(_props.projectPlannedStart);
  const today = normalizeBoardDate(_props.today) || todayJstDateString();
  if (!projectPlannedStart) return today;
  return projectPlannedStart < today ? today : projectPlannedStart;
}

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

export function getExplicitBoardTargetDate(_props: {
  analysisDateApplied: string;
  projectPlannedStart: string | null | undefined;
  today?: string;
}): string | null {
  const analysisDateApplied = normalizeBoardDate(_props.analysisDateApplied);
  const projectPlannedStart = normalizeBoardDate(_props.projectPlannedStart);
  const today = normalizeBoardDate(_props.today) || todayJstDateString();
  const implicitRequestTargetDate = projectPlannedStart || today;
  if (!analysisDateApplied) return null;
  if (analysisDateApplied === implicitRequestTargetDate) return null;
  return analysisDateApplied;
}

