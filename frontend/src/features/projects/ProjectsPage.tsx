import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import useSWR from "swr";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import { ProjectEditor } from "@/components/ProjectEditor";
import { apiGetWithPagination, apiSend } from "@/lib/api";
import type { ProjectRow } from "@/lib/types";

function parseEditProjectId(value: string | null): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

export function ProjectsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [editingProjectId, setEditingProjectId] = useState<number | null>(() =>
    parseEditProjectId(searchParams.get("edit")),
  );
  const [working, setWorking] = useState(false);
  const { data, error, isLoading, mutate } = useSWR("/projects", () =>
    apiGetWithPagination<ProjectRow[]>("/projects?per_page=200"),
  );

  useEffect(() => {
    const nextProjectId = parseEditProjectId(searchParams.get("edit"));
    setEditingProjectId((current) =>
      current === nextProjectId ? current : nextProjectId,
    );
  }, [searchParams]);

  function openProjectEditor(projectId: number | null) {
    setEditingProjectId(projectId);
    setSearchParams(
      (current) => {
        const next = new URLSearchParams(current);
        if (projectId == null) {
          next.delete("edit");
        } else {
          next.set("edit", String(projectId));
        }
        return next;
      },
      { replace: true },
    );
  }

  async function reserve(projectId: number) {
    setWorking(true);
    try {
      await apiSend(`/projects/${projectId}/reserve`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      await mutate();
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="space-y-6">
      <section>
        <h1 className="font-display text-3xl font-bold">Projects</h1>
        <p className="mt-1 text-sm text-slate-600">
          Plan future demand and requirement structure before execution-time reservations.
        </p>
        <p className="mt-1 text-xs text-slate-500">
          Use <span className="font-semibold">Workspace</span> for sequential shortage review and{" "}
          <span className="font-semibold">Procurement</span> for purchasing follow-up, then{" "}
          <span className="font-semibold">Reserve</span> when work is ready to consume real stock.
        </p>
      </section>

      <ProjectEditor
        projectId={editingProjectId}
        title={editingProjectId ? `Edit Project #${editingProjectId}` : "Create Project"}
        submitLabel={editingProjectId ? "Save Project" : "Create Project"}
        onCancel={editingProjectId ? () => openProjectEditor(null) : undefined}
        onSaved={async () => {
          openProjectEditor(null);
          await mutate();
        }}
      />

      <section className="panel p-4">
        <h2 className="mb-3 font-display text-lg font-semibold">Project List</h2>
        {isLoading && <p className="text-sm text-slate-500">Loading...</p>}
        {error && <ApiErrorNotice error={error} area="project data" />}
        {data?.data && (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="px-2 py-2">ID</th>
                  <th className="px-2 py-2">Name</th>
                  <th className="px-2 py-2">Status</th>
                  <th className="px-2 py-2">Planned Start</th>
                  <th className="px-2 py-2">Requirements</th>
                  <th className="px-2 py-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {data.data.map((row) => (
                  <tr key={row.project_id} className="border-b border-slate-100">
                    <td className="px-2 py-2">#{row.project_id}</td>
                    <td className="px-2 py-2 font-semibold">{row.name}</td>
                    <td className="px-2 py-2">{row.status}</td>
                    <td className="px-2 py-2">{row.planned_start ?? "-"}</td>
                    <td className="px-2 py-2">{row.requirement_count}</td>
                    <td className="px-2 py-2">
                      <button
                        className="button-subtle mr-2"
                        type="button"
                        onClick={() => openProjectEditor(row.project_id)}
                      >
                        Edit
                      </button>
                      <button
                        className="button-subtle"
                        type="button"
                        disabled={working}
                        onClick={() => void reserve(row.project_id)}
                      >
                        Reserve
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
