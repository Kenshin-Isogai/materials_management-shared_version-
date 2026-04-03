/** Shared import preview status type used across all import flows. */
export type PreviewStatus = "exact" | "high_confidence" | "needs_review" | "unresolved";

/** Summary shape common to all import preview responses. */
export type PreviewSummary = {
  total_rows: number;
  exact: number;
  high_confidence: number;
  needs_review: number;
  unresolved: number;
};

export function previewStatusLabel(status: PreviewStatus | string): string {
  switch (status) {
    case "exact":
      return "Exact";
    case "high_confidence":
      return "High Confidence";
    case "needs_review":
      return "Needs Review";
    case "unresolved":
      return "Unresolved";
    default:
      return status;
  }
}

export function previewStatusTone(status: PreviewStatus | string): string {
  switch (status) {
    case "exact":
      return "bg-emerald-50 text-emerald-700";
    case "high_confidence":
      return "bg-sky-50 text-sky-700";
    case "needs_review":
      return "bg-amber-50 text-amber-700";
    case "unresolved":
      return "bg-red-50 text-red-700";
    default:
      return "bg-slate-100 text-slate-700";
  }
}
