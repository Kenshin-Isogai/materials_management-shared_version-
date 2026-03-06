import { FormEvent, useMemo, useState } from "react";
import useSWR from "swr";
import { apiGetWithPagination, apiSend } from "../lib/api";
import { CatalogPicker } from "../components/CatalogPicker";
import { formatActionError, resolvePreviewSelection } from "../lib/previewState";
import type { CatalogSearchResult, Item } from "../lib/types";

type ProjectRow = {
  project_id: number;
  name: string;
  status: string;
  planned_start: string | null;
  requirement_count: number;
};

type ProjectRequirement = {
  requirement_id: number;
  assembly_id: number | null;
  item_id: number | null;
  quantity: number;
  requirement_type: "INITIAL" | "SPARE" | "REPLACEMENT";
  note: string | null;
};

type ProjectDetail = ProjectRow & {
  description: string | null;
  requirements: ProjectRequirement[];
};

type AssemblyOption = {
  assembly_id: number;
  name: string;
};

type RequirementRow = {
  target_type: "ITEM" | "ASSEMBLY";
  target_id: string;
  quantity: string;
  requirement_type: "INITIAL" | "SPARE" | "REPLACEMENT";
  note: string;
  target_query: string;
  match_status?: "matched" | "unregistered";
};

type ProjectRequirementPreviewMatch = CatalogSearchResult & {
  confidence_score?: number | null;
  match_reason?: string | null;
};

type ProjectRequirementPreviewRow = {
  row: number;
  raw_line: string;
  raw_target: string;
  quantity: string;
  quantity_raw: string;
  quantity_defaulted: boolean;
  status: "exact" | "high_confidence" | "needs_review" | "unresolved";
  message: string;
  requires_user_selection: boolean;
  allowed_entity_types: Array<"item">;
  suggested_match: ProjectRequirementPreviewMatch | null;
  candidates: ProjectRequirementPreviewMatch[];
};

type ProjectRequirementPreview = {
  summary: {
    total_rows: number;
    exact: number;
    high_confidence: number;
    needs_review: number;
    unresolved: number;
  };
  can_auto_accept: boolean;
  rows: ProjectRequirementPreviewRow[];
};

const blankRequirement = (): RequirementRow => ({
  target_type: "ITEM",
  target_id: "",
  quantity: "1",
  requirement_type: "INITIAL",
  note: "",
  target_query: "",
  match_status: undefined
});

function itemToCatalogResult(item: Item): CatalogSearchResult {
  return {
    entity_type: "item",
    entity_id: item.item_id,
    value_text: item.item_number,
    display_label: `${item.item_number} (${item.manufacturer_name}) #${item.item_id}`,
    summary: [item.category, `#${item.item_id}`].filter(Boolean).join(" | "),
    match_source: "item_number",
  };
}

function assemblyToCatalogResult(assembly: AssemblyOption): CatalogSearchResult {
  return {
    entity_type: "assembly",
    entity_id: assembly.assembly_id,
    value_text: assembly.name,
    display_label: `${assembly.name} #${assembly.assembly_id}`,
    summary: `Assembly #${assembly.assembly_id}`,
    match_source: "name",
  };
}

function projectPreviewMatchToCatalogResult(
  match: ProjectRequirementPreviewMatch
): CatalogSearchResult {
  return {
    entity_type: "item",
    entity_id: match.entity_id,
    value_text: match.value_text,
    display_label: match.display_label,
    summary: match.summary,
    match_source: match.match_source,
  };
}

function previewStatusTone(status: ProjectRequirementPreviewRow["status"]): string {
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

export function ProjectsPage() {
  const [name, setName] = useState("");
  const [status, setStatus] = useState("PLANNING");
  const [plannedStart, setPlannedStart] = useState("");
  const [requirements, setRequirements] = useState<RequirementRow[]>([
    blankRequirement(),
    blankRequirement()
  ]);
  const [loading, setLoading] = useState(false);
  const [entryListText, setEntryListText] = useState("");
  const [entryListWarnings, setEntryListWarnings] = useState<string[]>([]);
  const [entryPreview, setEntryPreview] = useState<ProjectRequirementPreview | null>(null);
  const [entryPreviewSelections, setEntryPreviewSelections] = useState<
    Record<number, CatalogSearchResult | null>
  >({});
  const [entryPreviewMessage, setEntryPreviewMessage] = useState("");
  const [editingProject, setEditingProject] = useState<ProjectDetail | null>(null);

  const { data, error, isLoading, mutate } = useSWR("/projects", () =>
    apiGetWithPagination<ProjectRow[]>("/projects?per_page=200")
  );
  const { data: itemsResp } = useSWR("/items-options-projects", () =>
    apiGetWithPagination<Item[]>("/items?per_page=1000")
  );
  const { data: assembliesResp } = useSWR("/assembly-options-projects", () =>
    apiGetWithPagination<AssemblyOption[]>("/assemblies?per_page=1000")
  );
  const items = itemsResp?.data ?? [];
  const assemblies = assembliesResp?.data ?? [];
  const itemCatalogById = useMemo(
    () => new Map(items.map((item) => [item.item_id, itemToCatalogResult(item)])),
    [items]
  );
  const assemblyCatalogById = useMemo(
    () => new Map(assemblies.map((assembly) => [assembly.assembly_id, assemblyToCatalogResult(assembly)])),
    [assemblies]
  );

  function updateRequirement(index: number, patch: Partial<RequirementRow>) {
    setRequirements((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function removeRequirement(index: number) {
    setRequirements((prev) => prev.filter((_, i) => i !== index));
  }

  function resetEntryPreview() {
    setEntryPreview(null);
    setEntryPreviewSelections({});
  }

  function applyEntryPreview(preview: ProjectRequirementPreview) {
    const nextSelections: Record<number, CatalogSearchResult | null> = {};
    for (const row of preview.rows) {
      nextSelections[row.row] =
        row.suggested_match && row.status !== "needs_review" && row.status !== "unresolved"
          ? projectPreviewMatchToCatalogResult(row.suggested_match)
          : null;
    }
    setEntryPreview(preview);
    setEntryPreviewSelections(nextSelections);
  }

  function selectedEntryPreviewMatch(
    row: ProjectRequirementPreviewRow
  ): CatalogSearchResult | null {
    const fallbackSelection =
      !row.suggested_match || row.status === "needs_review" || row.status === "unresolved"
        ? null
        : projectPreviewMatchToCatalogResult(row.suggested_match);
    return resolvePreviewSelection(entryPreviewSelections, row.row, fallbackSelection);
  }

  async function createProject(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      const payloadRequirements = requirements
        .filter((row) => row.target_id && Number(row.quantity) > 0)
        .map((row) => {
          const base = {
            quantity: Number(row.quantity),
            requirement_type: row.requirement_type,
            note: row.note.trim() || null
          };
          if (row.target_type === "ITEM") {
            return { ...base, item_id: Number(row.target_id), assembly_id: null };
          }
          return { ...base, assembly_id: Number(row.target_id), item_id: null };
        });
      await apiSend("/projects", {
        method: "POST",
        body: JSON.stringify({
          name,
          status,
          planned_start: plannedStart || null,
          requirements: payloadRequirements
        })
      });
      setName("");
      setRequirements([blankRequirement(), blankRequirement()]);
      setEntryListText("");
      setEntryListWarnings([]);
      setEntryPreviewMessage("");
      resetEntryPreview();
      await mutate();
    } finally {
      setLoading(false);
    }
  }

  async function startEdit(projectId: number) {
    const resp = await apiSend<ProjectDetail>(`/projects/${projectId}`, { method: "GET" });
    setEditingProject(resp);
    setName(resp.name);
      setStatus(resp.status);
      setPlannedStart(resp.planned_start ?? "");
      setEntryPreviewMessage("");
      resetEntryPreview();
      setRequirements(
        resp.requirements.length
        ? resp.requirements.map((req) => ({
            target_type: req.item_id ? "ITEM" : "ASSEMBLY",
            target_id: String(req.item_id ?? req.assembly_id ?? ""),
            quantity: String(req.quantity),
            requirement_type: req.requirement_type,
            note: req.note ?? "",
            target_query: "",
            match_status: "matched"
          }))
        : [blankRequirement(), blankRequirement()]
    );
  }

  async function saveEdit(event: FormEvent) {
    event.preventDefault();
    if (!editingProject) return;
    setLoading(true);
    try {
      const payloadRequirements = requirements
        .filter((row) => row.target_id && Number(row.quantity) > 0)
        .map((row) => {
          const base = {
            quantity: Number(row.quantity),
            requirement_type: row.requirement_type,
            note: row.note.trim() || null
          };
          if (row.target_type === "ITEM") {
            return { ...base, item_id: Number(row.target_id), assembly_id: null };
          }
          return { ...base, assembly_id: Number(row.target_id), item_id: null };
        });

      await apiSend(`/projects/${editingProject.project_id}`, {
        method: "PUT",
        body: JSON.stringify({
          name,
          status,
          planned_start: plannedStart || null,
          requirements: payloadRequirements
        })
      });
      setEditingProject(null);
      setName("");
      setStatus("PLANNING");
      setPlannedStart("");
      setRequirements([blankRequirement(), blankRequirement()]);
      setEntryListText("");
      setEntryListWarnings([]);
      setEntryPreviewMessage("");
      resetEntryPreview();
      await mutate();
    } finally {
      setLoading(false);
    }
  }

  async function previewEntryList() {
    if (!entryListText.trim()) return;
    setLoading(true);
    setEntryPreviewMessage("");
    resetEntryPreview();
    try {
      const preview = await apiSend<ProjectRequirementPreview>("/projects/requirements/preview", {
        method: "POST",
        body: JSON.stringify({ text: entryListText }),
      });
      applyEntryPreview(preview);
      setEntryPreviewMessage(
        preview.can_auto_accept
          ? `Preview ready: ${preview.summary.total_rows} row(s) are ready to apply.`
          : `Preview ready: review=${preview.summary.needs_review}, unresolved=${preview.summary.unresolved}.`
      );
    } catch (error) {
      setEntryPreviewMessage(formatActionError("Preview failed", error));
    } finally {
      setLoading(false);
    }
  }

  function applyEntryPreviewToRequirements() {
    if (!entryPreview) return;
    const nextRequirements = entryPreview.rows.map((row) => {
      const selection = selectedEntryPreviewMatch(row);
      if (selection) {
        return {
          ...blankRequirement(),
          target_type: "ITEM" as const,
          target_id: String(selection.entity_id),
          target_query: selection.display_label,
          quantity: row.quantity,
          match_status: "matched" as const,
        };
      }
      return {
        ...blankRequirement(),
        target_type: "ITEM" as const,
        target_query: row.raw_target,
        quantity: row.quantity,
        match_status: "unregistered" as const,
      };
    });
    if (nextRequirements.length > 0) {
      setRequirements(nextRequirements);
    }
    setEntryListWarnings(
      entryPreview.rows
        .filter((row) => !selectedEntryPreviewMatch(row))
        .map((row) => row.message)
    );
    setEntryPreviewMessage(`Applied ${entryPreview.rows.length} preview row(s) to requirements.`);
    resetEntryPreview();
  }

  async function reserve(projectId: number) {
    setLoading(true);
    try {
      await apiSend(`/projects/${projectId}/reserve`, { method: "POST", body: JSON.stringify({}) });
    } finally {
      setLoading(false);
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
          Use <span className="font-semibold">Planning</span> for sequential shortage/RFQ analysis, then <span className="font-semibold">Reservations</span> when work is ready to consume real stock.
        </p>
      </section>

      <section className="panel p-4">
        <h2 className="mb-3 font-display text-lg font-semibold">
          {editingProject ? `Edit Project #${editingProject.project_id}` : "Create Project"}
        </h2>
        <form className="grid gap-3 md:grid-cols-3" onSubmit={editingProject ? saveEdit : createProject}>
          <input
            className="input"
            placeholder="Project name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option>PLANNING</option>
            <option>CONFIRMED</option>
            <option>ACTIVE</option>
            <option>COMPLETED</option>
            <option>CANCELLED</option>
          </select>
          <input
            className="input"
            type="date"
            value={plannedStart}
            onChange={(e) => setPlannedStart(e.target.value)}
          />
          <div className="md:col-span-3">
            <div className="mb-3 rounded-md border border-slate-200 bg-slate-50 p-3">
              <p className="text-xs font-semibold text-slate-600">Quick item list input</p>
              <p className="mb-2 text-xs text-slate-500">Paste one line per item: item_number,quantity</p>
              <textarea
                className="input min-h-[88px]"
                placeholder={"LAS-001,2\nMIRROR-19,4"}
                value={entryListText}
                onChange={(e) => {
                  setEntryListText(e.target.value);
                  setEntryPreviewMessage("");
                  resetEntryPreview();
                }}
              />
              <div className="mt-2 flex items-center gap-2">
                <button className="button-subtle" type="button" onClick={() => void previewEntryList()}>
                  Preview Parse
                </button>
                {!!entryListWarnings.length && (
                  <span className="text-xs font-semibold text-amber-700">
                    {entryListWarnings.length} row(s) still need follow-up
                  </span>
                )}
              </div>
              {entryPreviewMessage && (
                <p className="mt-2 text-xs text-slate-600">{entryPreviewMessage}</p>
              )}
              {entryPreview && (
                <div className="mt-3 rounded-xl border border-slate-200 bg-white p-3">
                  <div className="flex flex-wrap gap-2 text-xs">
                    <span className="rounded-full bg-emerald-50 px-3 py-1 font-semibold text-emerald-700">
                      Exact {entryPreview.summary.exact}
                    </span>
                    <span className="rounded-full bg-sky-50 px-3 py-1 font-semibold text-sky-700">
                      High Confidence {entryPreview.summary.high_confidence}
                    </span>
                    <span className="rounded-full bg-amber-50 px-3 py-1 font-semibold text-amber-700">
                      Review {entryPreview.summary.needs_review}
                    </span>
                    <span className="rounded-full bg-red-50 px-3 py-1 font-semibold text-red-700">
                      Unresolved {entryPreview.summary.unresolved}
                    </span>
                  </div>
                  <div className="mt-3 overflow-x-auto">
                    <table className="min-w-[1100px] text-sm">
                      <thead>
                        <tr className="border-b border-slate-200 text-left text-slate-500">
                          <th className="px-2 py-2">Line</th>
                          <th className="px-2 py-2">Raw Input</th>
                          <th className="px-2 py-2">Qty</th>
                          <th className="px-2 py-2">Resolved Item</th>
                          <th className="px-2 py-2">Status</th>
                          <th className="px-2 py-2">Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {entryPreview.rows.map((row) => (
                          <tr key={row.row} className="border-b border-slate-100 align-top">
                            <td className="px-2 py-3 font-semibold">#{row.row}</td>
                            <td className="px-2 py-3">
                              <div className="space-y-1">
                                <p className="font-semibold text-slate-900">{row.raw_target || "(blank)"}</p>
                                <p className="text-xs text-slate-500">{row.raw_line}</p>
                                {row.quantity_defaulted && (
                                  <p className="text-xs font-semibold text-amber-700">
                                    Invalid quantity defaulted to 1
                                  </p>
                                )}
                              </div>
                            </td>
                            <td className="px-2 py-3">{row.quantity}</td>
                            <td className="px-2 py-3">
                              {selectedEntryPreviewMatch(row) ? (
                                <div className="space-y-1">
                                  <p className="font-semibold text-slate-900">
                                    {selectedEntryPreviewMatch(row)?.display_label}
                                  </p>
                                  {selectedEntryPreviewMatch(row)?.summary && (
                                    <p className="text-xs text-slate-500">
                                      {selectedEntryPreviewMatch(row)?.summary}
                                    </p>
                                  )}
                                </div>
                              ) : row.suggested_match ? (
                                <div className="space-y-1">
                                  <p className="font-semibold text-slate-900">
                                    {row.suggested_match.display_label}
                                  </p>
                                  {row.suggested_match.summary && (
                                    <p className="text-xs text-slate-500">{row.suggested_match.summary}</p>
                                  )}
                                </div>
                              ) : (
                                <p className="text-sm text-slate-500">No resolved item</p>
                              )}
                            </td>
                            <td className="px-2 py-3">
                              <span
                                className={`inline-flex rounded-full px-3 py-1 text-xs font-semibold ${previewStatusTone(row.status)}`}
                              >
                                {row.status}
                              </span>
                            </td>
                            <td className="px-2 py-3">
                              <div className="space-y-2">
                                <p className="text-xs text-slate-600">{row.message}</p>
                                {row.allowed_entity_types.length > 0 && (
                                  <CatalogPicker
                                    allowedTypes={row.allowed_entity_types}
                                    onChange={(value) =>
                                      setEntryPreviewSelections((prev) => ({
                                        ...prev,
                                        [row.row]: value,
                                      }))
                                    }
                                    placeholder="Select item"
                                    recentKey="project-requirement-preview-item"
                                    seedQuery={row.raw_target}
                                    value={selectedEntryPreviewMatch(row)}
                                  />
                                )}
                                {row.candidates.length > 1 && (
                                  <p className="text-xs text-slate-500">
                                    Candidates:{" "}
                                    {row.candidates
                                      .slice(0, 3)
                                      .map((candidate) => candidate.display_label)
                                      .join(" | ")}
                                  </p>
                                )}
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <div className="mt-3 flex gap-2">
                    <button className="button" type="button" onClick={applyEntryPreviewToRequirements}>
                      Apply To Requirements
                    </button>
                    <button className="button-subtle" type="button" onClick={resetEntryPreview}>
                      Clear Preview
                    </button>
                  </div>
                </div>
              )}
            </div>
            <div className="mb-2 flex items-center justify-between">
              <p className="text-sm font-semibold text-slate-700">Requirements</p>
              <button
                className="button-subtle"
                type="button"
                onClick={() => setRequirements((prev) => [...prev, blankRequirement()])}
              >
                Add Row
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-[980px] text-sm no-sticky-header">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-slate-500">
                    <th className="px-2 py-2">Target Type</th>
                    <th className="px-2 py-2">Target</th>
                    <th className="px-2 py-2">Qty</th>
                    <th className="px-2 py-2">Requirement Type</th>
                    <th className="px-2 py-2">Note</th>
                    <th className="px-2 py-2">-</th>
                  </tr>
                </thead>
                <tbody>
                  {requirements.map((row, idx) => (
                    <tr key={idx} className="border-b border-slate-100">
                      <td className="px-2 py-2">
                        <select
                          className="input"
                          value={row.target_type}
                          onChange={(e) =>
                            updateRequirement(idx, {
                              target_type: e.target.value as RequirementRow["target_type"],
                              target_id: "",
                              target_query: "",
                              match_status: undefined
                            })
                          }
                        >
                          <option value="ITEM">ITEM</option>
                          <option value="ASSEMBLY">ASSEMBLY</option>
                        </select>
                      </td>
                      <td className="px-2 py-2">
                        {row.target_type === "ITEM" ? (
                          <CatalogPicker
                            allowedTypes={["item"]}
                            onChange={(value) =>
                              updateRequirement(idx, {
                                target_id: value ? String(value.entity_id) : "",
                                target_query: value?.display_label ?? "",
                                match_status: value ? "matched" : undefined
                              })
                            }
                            placeholder="Search items"
                            recentKey="project-requirement-item"
                            seedQuery={row.target_query}
                            value={
                              row.target_id
                                ? itemCatalogById.get(Number(row.target_id)) ?? null
                                : null
                            }
                          />
                        ) : (
                          <CatalogPicker
                            allowedTypes={["assembly"]}
                            onChange={(value) =>
                              updateRequirement(idx, {
                                target_id: value ? String(value.entity_id) : "",
                                target_query: value?.display_label ?? "",
                                match_status: value ? "matched" : undefined
                              })
                            }
                            placeholder="Search assemblies"
                            recentKey="project-requirement-assembly"
                            value={
                              row.target_id
                                ? assemblyCatalogById.get(Number(row.target_id)) ?? null
                                : null
                            }
                          />
                        )}
                        {row.match_status === "unregistered" && (
                          <p className="mt-1 text-xs font-semibold text-amber-700">No registered item matched.</p>
                        )}
                      </td>
                      <td className="px-2 py-2">
                        <input
                          className="input"
                          type="number"
                          min={1}
                          value={row.quantity}
                          onChange={(e) => updateRequirement(idx, { quantity: e.target.value })}
                        />
                      </td>
                      <td className="px-2 py-2">
                        <select
                          className="input"
                          value={row.requirement_type}
                          onChange={(e) =>
                            updateRequirement(
                              idx,
                              { requirement_type: e.target.value as RequirementRow["requirement_type"] }
                            )
                          }
                        >
                          <option value="INITIAL">INITIAL</option>
                          <option value="SPARE">SPARE</option>
                          <option value="REPLACEMENT">REPLACEMENT</option>
                        </select>
                      </td>
                      <td className="px-2 py-2">
                        <input
                          className="input"
                          value={row.note}
                          onChange={(e) => updateRequirement(idx, { note: e.target.value })}
                        />
                      </td>
                      <td className="px-2 py-2">
                        <button className="button-subtle" type="button" onClick={() => removeRequirement(idx)}>
                          Del
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div className="flex gap-2 md:col-span-3">
            <button className="button" disabled={loading} type="submit">
              {editingProject ? "Save Project" : "Create Project"}
            </button>
            {editingProject && (
              <button
                className="button-subtle"
                type="button"
                onClick={() => {
                  setEditingProject(null);
                  setName("");
                  setStatus("PLANNING");
                  setPlannedStart("");
                  setEntryListText("");
                  setEntryListWarnings([]);
                  setEntryPreviewMessage("");
                  resetEntryPreview();
                  setRequirements([blankRequirement(), blankRequirement()]);
                }}
              >
                Cancel Edit
              </button>
            )}
          </div>
        </form>
      </section>

      <section className="panel p-4">
        <h2 className="mb-3 font-display text-lg font-semibold">Project List</h2>
        {isLoading && <p className="text-sm text-slate-500">Loading...</p>}
        {error && <p className="text-sm text-red-600">{String(error)}</p>}
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
                      <button className="button-subtle mr-2" onClick={() => startEdit(row.project_id)}>
                        Edit
                      </button>
                      <button className="button-subtle" onClick={() => reserve(row.project_id)}>
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
