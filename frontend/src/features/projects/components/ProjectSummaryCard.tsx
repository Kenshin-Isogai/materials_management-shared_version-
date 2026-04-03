import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";
import type { WorkspaceProjectSummary } from "@/lib/types";
import { projectBoardRoute, projectEditorRoute } from "@/features/projects/routes";

function statusTone(status: string): string {
  switch (status) {
    case "ACTIVE":
      return "bg-emerald-100 text-emerald-800";
    case "CONFIRMED":
      return "bg-sky-100 text-sky-800";
    case "PLANNING":
      return "bg-amber-100 text-amber-800";
    case "COMPLETED":
      return "bg-slate-200 text-slate-700";
    case "CANCELLED":
      return "bg-rose-100 text-rose-800";
    default:
      return "bg-slate-100 text-slate-700";
  }
}

function summaryTone(mode: WorkspaceProjectSummary["summary_mode"]): string {
  switch (mode) {
    case "authoritative":
      return "border-emerald-200 bg-emerald-50 text-emerald-800";
    case "preview_required":
      return "border-amber-200 bg-amber-50 text-amber-800";
    default:
      return "border-slate-200 bg-slate-50 text-slate-700";
  }
}

function formatDate(value: string | null | undefined): string {
  return value && value.trim() ? value : "-";
}

function SummaryMetric({
  label,
  value,
  tone = "slate",
}: {
  label: string;
  value: number | string;
  tone?: "slate" | "amber" | "emerald" | "sky";
}) {
  const toneClass =
    tone === "amber"
      ? "border-amber-200 bg-amber-50 text-amber-900"
      : tone === "emerald"
        ? "border-emerald-200 bg-emerald-50 text-emerald-900"
        : tone === "sky"
          ? "border-sky-200 bg-sky-50 text-sky-900"
          : "border-slate-200 bg-slate-50 text-slate-900";
  return (
    <div className={cn("rounded-2xl border px-4 py-3", toneClass)}>
      <p className="text-xs font-semibold uppercase tracking-wide opacity-70">
        {label}
      </p>
      <p className="mt-1 text-2xl font-bold">{value}</p>
    </div>
  );
}

export function ProjectSummaryCard({
  project,
  selected,
}: {
  project: WorkspaceProjectSummary;
  selected: boolean;
}) {
  const planningSummary = project.planning_summary;
  const procurementSummary = project.procurement_summary;
  return (
    <article
      className={cn("panel p-4 transition", selected && "ring-2 ring-slate-800/20")}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-display text-xl font-semibold">
              {project.name}
            </h3>
            <span
              className={cn(
                "rounded-full px-2 py-1 text-xs font-semibold",
                statusTone(project.status),
              )}
            >
              {project.status}
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-600">
            Start {formatDate(project.planned_start)} | Requirements{" "}
            {project.requirement_count}
          </p>
          {project.description && (
            <p className="mt-2 text-sm text-slate-600">
              {project.description}
            </p>
          )}
        </div>
        <div
          className={cn(
            "rounded-2xl border px-3 py-2 text-xs font-medium",
            summaryTone(project.summary_mode),
          )}
        >
          {project.summary_mode === "authoritative"
            ? "Live Pipeline"
            : project.summary_mode === "preview_required"
              ? "Preview Required"
              : "Archived"}
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {planningSummary ? (
          <>
            <SummaryMetric
              label="Required"
              value={planningSummary.required_total}
            />
            <SummaryMetric
              label="On-Time Gap"
              value={planningSummary.shortage_at_start_total}
              tone="amber"
            />
            <SummaryMetric
              label="Remaining"
              value={planningSummary.remaining_shortage_total}
            />
            <SummaryMetric
              label="Generic Before"
              value={planningSummary.cumulative_generic_consumed_before_total}
              tone="sky"
            />
          </>
        ) : (
          <>
            <SummaryMetric
              label="Required Rows"
              value={project.requirement_count}
            />
            <SummaryMetric
              label="Open Batches"
              value={procurementSummary.open_batch_count}
              tone="amber"
            />
            <SummaryMetric
              label="Quoted Lines"
              value={procurementSummary.quoted_line_count}
              tone="emerald"
            />
            <SummaryMetric
              label="Ordered Lines"
              value={procurementSummary.ordered_line_count}
              tone="sky"
            />
          </>
        )}
      </div>

      <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
        <p>{project.summary_message}</p>
        <p className="mt-1 text-xs text-slate-500">
          Procurement: {procurementSummary.open_batch_count} open batches,{" "}
          {procurementSummary.quoted_line_count} quoted lines,{" "}
          {procurementSummary.ordered_line_count} ordered lines.
        </p>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <Link
          className="button-subtle"
          to={projectEditorRoute(project.project_id)}
        >
          Open Project
        </Link>
        <Link
          className="button"
          to={projectBoardRoute(project.project_id)}
        >
          {project.status === "PLANNING" ? "Preview In Board" : "Open Board"}
        </Link>
        <Link
          className="button-subtle"
          to="/procurement"
        >
          RFQ Context
        </Link>
      </div>
    </article>
  );
}
