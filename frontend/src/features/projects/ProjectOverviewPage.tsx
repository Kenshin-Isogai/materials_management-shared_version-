import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import useSWR from "swr";
import { cn } from "@/lib/utils";
import { StatusCallout } from "@/components/StatusCallout";
import { apiGet } from "@/lib/api";
import {
  isAuthError,
  isBackendUnavailableError,
  presentApiError,
} from "@/lib/errorUtils";
import type {
  WorkspaceProjectSummary,
  WorkspaceSummary,
} from "@/lib/types";
import { ProjectSummaryCard } from "./components/ProjectSummaryCard";
import { projectBoardRoute, projectEditorRoute } from "@/features/projects/routes";

type WorkspaceView = "summary" | "pipeline";

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

function renderWorkspaceError(error: unknown, area: string) {
  if (isAuthError(error)) {
    return (
      <StatusCallout
        title="Sign-in required"
        message={`Sign in with an allowed account to load ${area}.`}
        tone="error"
      />
    );
  }
  if (isBackendUnavailableError(error)) {
    return (
      <StatusCallout
        title="Environment unavailable"
        message={`${area} is unavailable because the backend or database is not ready. If this is dev or staging, start Cloud SQL and try again.`}
        tone="warning"
      />
    );
  }
  return <p className="text-sm text-red-600">{presentApiError(error)}</p>;
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

export function ProjectOverviewPage() {
  const [view, setView] = useState<WorkspaceView>("summary");

  const {
    data: workspaceSummary,
    error: workspaceError,
    isLoading: workspaceLoading,
  } = useSWR("/workspace/summary", () =>
    apiGet<WorkspaceSummary>("/workspace/summary"),
  );

  const projects = workspaceSummary?.projects ?? [];
  const pipeline = workspaceSummary?.pipeline ?? [];

  const statusCounts = useMemo(
    () => ({
      active: projects.filter((p) => p.status === "ACTIVE").length,
      confirmed: projects.filter((p) => p.status === "CONFIRMED").length,
      planning: projects.filter((p) => p.status === "PLANNING").length,
    }),
    [projects],
  );

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold">
            Project Overview
          </h1>
          <p className="mt-1 text-sm text-slate-600">
            Summary-first planning surface for Projects, sequential netting,
            and procurement follow-up.
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Related pages:{" "}
            <Link
              className="font-semibold text-slate-700 underline"
              to="/projects"
            >
              Projects
            </Link>
            ,{" "}
            <Link
              className="font-semibold text-slate-700 underline"
              to="/procurement"
            >
              Procurement
            </Link>
            .
          </p>
        </div>
        <div className="grid min-w-[280px] gap-3 sm:grid-cols-3">
          <SummaryMetric
            label="Active"
            value={statusCounts.active}
            tone="emerald"
          />
          <SummaryMetric
            label="Confirmed"
            value={statusCounts.confirmed}
            tone="sky"
          />
          <SummaryMetric
            label="Planning"
            value={statusCounts.planning}
            tone="amber"
          />
        </div>
      </section>

      <section className="flex flex-wrap gap-2">
        <button
          className={cn(
            "button-subtle",
            view === "summary" && "border-slate-800 bg-slate-800 text-white",
          )}
          type="button"
          onClick={() => setView("summary")}
        >
          Project Summary
        </button>
        <button
          className={cn(
            "button-subtle",
            view === "pipeline" && "border-slate-800 bg-slate-800 text-white",
          )}
          type="button"
          onClick={() => setView("pipeline")}
        >
          Pipeline
        </button>
      </section>

      {workspaceError && renderWorkspaceError(workspaceError, "workspace data")}
      {workspaceLoading && (
        <p className="text-sm text-slate-500">Loading workspace summary...</p>
      )}

      {view === "summary" && (
        <section className="grid gap-4 xl:grid-cols-2">
          {projects.map((project) => (
            <ProjectSummaryCard
              key={project.project_id}
              project={project}
              selected={false}
            />
          ))}
          {!projects.length && !workspaceLoading && (
            <div className="panel p-6 text-sm text-slate-500">
              No projects available yet.
            </div>
          )}
        </section>
      )}

      {view === "pipeline" && (
        <section className="panel p-4">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-display text-xl font-semibold">
                Committed Pipeline
              </h2>
              <p className="text-sm text-slate-600">
                Committed projects are netted in planned-start order. Earlier
                backlog consumes later generic arrivals before newer projects
                can use them.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Link className="button-subtle" to="/procurement">
                Open Procurement Page
              </Link>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-[1180px] text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="px-2 py-2">Project</th>
                  <th className="px-2 py-2">Status</th>
                  <th className="px-2 py-2">Start</th>
                  <th className="px-2 py-2">Required</th>
                  <th className="px-2 py-2">Covered On Time</th>
                  <th className="px-2 py-2">On-Time Gap</th>
                  <th className="px-2 py-2">Remaining</th>
                  <th className="px-2 py-2">Generic Committed</th>
                  <th className="px-2 py-2">Generic Before</th>
                  <th className="px-2 py-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {pipeline.map((row) => (
                  <tr key={row.project_id} className="border-b border-slate-100">
                    <td className="px-2 py-3">
                      <p className="font-semibold">{row.name}</p>
                      <p className="text-xs text-slate-500">
                        #{row.project_id}
                      </p>
                    </td>
                    <td className="px-2 py-3">
                      <span
                        className={cn(
                          "rounded-full px-2 py-1 text-xs font-semibold",
                          statusTone(row.status),
                        )}
                      >
                        {row.status}
                      </span>
                    </td>
                    <td className="px-2 py-3">{row.planned_start}</td>
                    <td className="px-2 py-3">{row.required_total}</td>
                    <td className="px-2 py-3">{row.covered_on_time_total}</td>
                    <td className="px-2 py-3 font-semibold text-amber-700">
                      {row.shortage_at_start_total}
                    </td>
                    <td className="px-2 py-3">
                      {row.remaining_shortage_total}
                    </td>
                    <td className="px-2 py-3">
                      {row.generic_committed_total}
                    </td>
                    <td className="px-2 py-3">
                      {row.cumulative_generic_consumed_before_total}
                    </td>
                    <td className="px-2 py-3">
                      <div className="flex flex-wrap gap-2">
                        <Link
                          className="button-subtle"
                          to={projectEditorRoute(row.project_id)}
                        >
                          Project
                        </Link>
                        <Link
                          className="button"
                          to={projectBoardRoute(row.project_id)}
                        >
                          Board
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))}
                {!pipeline.length && (
                  <tr>
                    <td
                      className="px-2 py-5 text-slate-500"
                      colSpan={10}
                    >
                      No committed projects in the planning pipeline.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
