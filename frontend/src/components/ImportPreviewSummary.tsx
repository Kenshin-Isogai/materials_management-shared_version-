import type { PreviewSummary } from "@/lib/previewStatus";

type Props = {
  summary: PreviewSummary;
};

export function ImportPreviewSummary({ summary }: Props) {
  return (
    <div className="flex flex-wrap gap-2 text-xs">
      <span className="rounded-full bg-emerald-50 px-3 py-1 font-semibold text-emerald-700">
        Exact {summary.exact}
      </span>
      <span className="rounded-full bg-sky-50 px-3 py-1 font-semibold text-sky-700">
        High {summary.high_confidence}
      </span>
      <span className="rounded-full bg-amber-50 px-3 py-1 font-semibold text-amber-700">
        Review {summary.needs_review}
      </span>
      <span className="rounded-full bg-red-50 px-3 py-1 font-semibold text-red-700">
        Unresolved {summary.unresolved}
      </span>
    </div>
  );
}
