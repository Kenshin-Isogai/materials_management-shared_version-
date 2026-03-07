import { FormEvent, useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { apiGet, apiGetWithPagination, apiSend } from "../lib/api";
import {
  blankRequirementDraft,
  normalizeRequirementDrafts,
  type RequirementDraft,
} from "../lib/editorDrafts";
import { formatActionError, resolvePreviewSelection } from "../lib/previewState";
import type {
  AssemblyOption,
  CatalogSearchResult,
  Item,
  ProjectDetail,
  ProjectRequirementPreview,
  ProjectRequirementPreviewMatch,
  ProjectRequirementPreviewRow,
  ProjectStatus,
} from "../lib/types";
import { CatalogPicker } from "./CatalogPicker";

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
  match: ProjectRequirementPreviewMatch,
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

function buildRequirementsFromProject(project: ProjectDetail | null | undefined): RequirementDraft[] {
  if (!project?.requirements.length) {
    return [blankRequirementDraft(), blankRequirementDraft()];
  }
  return project.requirements.map((requirement) => ({
    target_type: requirement.item_id ? "ITEM" : "ASSEMBLY",
    target_id: String(requirement.item_id ?? requirement.assembly_id ?? ""),
    quantity: String(requirement.quantity),
    requirement_type: requirement.requirement_type,
    note: requirement.note ?? "",
    target_query: requirement.item_id
      ? [requirement.item_number, `#${requirement.item_id}`].filter(Boolean).join(" ")
      : [requirement.assembly_name, `#${requirement.assembly_id}`].filter(Boolean).join(" "),
    match_status: "matched",
  }));
}

function buildRequirementPayload(requirements: RequirementDraft[]) {
  return requirements
    .filter((row) => row.target_id && Number(row.quantity) > 0)
    .map((row) => {
      const base = {
        quantity: Number(row.quantity),
        requirement_type: row.requirement_type,
        note: row.note.trim() || null,
      };
      if (row.target_type === "ITEM") {
        return { ...base, item_id: Number(row.target_id), assembly_id: null };
      }
      return { ...base, assembly_id: Number(row.target_id), item_id: null };
    });
}

function buildEditorSignature(args: {
  name: string;
  status: ProjectStatus;
  plannedStart: string;
  requirements: RequirementDraft[];
}): string {
  return JSON.stringify({
    name: args.name.trim(),
    status: args.status,
    plannedStart: args.plannedStart.trim(),
    requirements: normalizeRequirementDrafts(args.requirements),
  });
}

type ProjectEditorProps = {
  projectId?: number | null;
  title?: string;
  submitLabel?: string;
  surfaceClassName?: string;
  autoFocusField?: "name" | "planned_start";
  onCancel?: () => void;
  onSaved?: (projectId: number) => Promise<void> | void;
  onDirtyChange?: (isDirty: boolean) => void;
  onOpenItem?: (itemId: number, label: string) => void;
  active?: boolean;
};

export function ProjectEditor({
  projectId = null,
  title,
  submitLabel,
  surfaceClassName = "panel p-4",
  autoFocusField = "name",
  onCancel,
  onSaved,
  onDirtyChange,
  onOpenItem,
  active = true,
}: ProjectEditorProps) {
  const isEditing = projectId != null;
  const { data: projectData, error: projectError, isLoading: projectLoading, mutate: mutateProject } = useSWR(
    active && isEditing ? `/projects/${projectId}` : null,
    () => apiGet<ProjectDetail>(`/projects/${projectId}`),
  );
  const { data: itemsResp } = useSWR(active ? "/items-options-project-editor" : null, () =>
    apiGetWithPagination<Item[]>("/items?per_page=1000"),
  );
  const { data: assembliesResp } = useSWR(active ? "/assembly-options-project-editor" : null, () =>
    apiGetWithPagination<AssemblyOption[]>("/assemblies?per_page=1000"),
  );

  const [name, setName] = useState("");
  const [status, setStatus] = useState<ProjectStatus>("PLANNING");
  const [plannedStart, setPlannedStart] = useState("");
  const [requirements, setRequirements] = useState<RequirementDraft[]>([
    blankRequirementDraft(),
    blankRequirementDraft(),
  ]);
  const [entryListText, setEntryListText] = useState("");
  const [entryListWarnings, setEntryListWarnings] = useState<string[]>([]);
  const [entryPreview, setEntryPreview] = useState<ProjectRequirementPreview | null>(null);
  const [entryPreviewSelections, setEntryPreviewSelections] = useState<
    Record<number, CatalogSearchResult | null>
  >({});
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [baselineSignature, setBaselineSignature] = useState(
    buildEditorSignature({
      name: "",
      status: "PLANNING",
      plannedStart: "",
      requirements: [blankRequirementDraft(), blankRequirementDraft()],
    }),
  );
  const [loadedProjectId, setLoadedProjectId] = useState<number | null>(null);

  const items = itemsResp?.data ?? [];
  const assemblies = assembliesResp?.data ?? [];
  const itemCatalogById = useMemo(
    () => new Map(items.map((item) => [item.item_id, itemToCatalogResult(item)])),
    [items],
  );
  const assemblyCatalogById = useMemo(
    () => new Map(assemblies.map((assembly) => [assembly.assembly_id, assemblyToCatalogResult(assembly)])),
    [assemblies],
  );

  function selectedRequirementCatalogResult(row: RequirementDraft): CatalogSearchResult | null {
    if (!row.target_id) return null;
    const targetId = Number(row.target_id);
    if (!Number.isFinite(targetId) || targetId <= 0) return null;
    if (row.target_type === "ITEM") {
      return (
        itemCatalogById.get(targetId) ?? {
          entity_type: "item",
          entity_id: targetId,
          value_text: row.target_query || `Item #${targetId}`,
          display_label: row.target_query || `Item #${targetId}`,
          summary: `#${targetId}`,
          match_source: null,
        }
      );
    }
    return (
      assemblyCatalogById.get(targetId) ?? {
        entity_type: "assembly",
        entity_id: targetId,
        value_text: row.target_query || `Assembly #${targetId}`,
        display_label: row.target_query || `Assembly #${targetId}`,
        summary: `Assembly #${targetId}`,
        match_source: null,
      }
    );
  }

  function resetPreviewState() {
    setEntryPreview(null);
    setEntryPreviewSelections({});
  }

  function resetToBlank() {
    const blankRows = [blankRequirementDraft(), blankRequirementDraft()];
    setName("");
    setStatus("PLANNING");
    setPlannedStart("");
    setRequirements(blankRows);
    setEntryListText("");
    setEntryListWarnings([]);
    setMessage("");
    resetPreviewState();
    setBaselineSignature(
      buildEditorSignature({
        name: "",
        status: "PLANNING",
        plannedStart: "",
        requirements: blankRows,
      }),
    );
  }

  function loadProjectIntoEditor(project: ProjectDetail) {
    const nextRequirements = buildRequirementsFromProject(project);
    setName(project.name);
    setStatus(project.status);
    setPlannedStart(project.planned_start ?? "");
    setRequirements(nextRequirements);
    setEntryListText("");
    setEntryListWarnings([]);
    setMessage("");
    resetPreviewState();
    setBaselineSignature(
      buildEditorSignature({
        name: project.name,
        status: project.status,
        plannedStart: project.planned_start ?? "",
        requirements: nextRequirements,
      }),
    );
  }

  useEffect(() => {
    if (!isEditing) {
      if (loadedProjectId != null) {
        resetToBlank();
        setLoadedProjectId(null);
      }
      return;
    }
    if (!projectData) return;
    if (loadedProjectId === projectData.project_id) return;
    loadProjectIntoEditor(projectData);
    setLoadedProjectId(projectData.project_id);
  }, [isEditing, loadedProjectId, projectData]);

  const currentSignature = useMemo(
    () =>
      buildEditorSignature({
        name,
        status,
        plannedStart,
        requirements,
      }),
    [name, plannedStart, requirements, status],
  );
  const hasAuxiliaryDraft =
    entryListText.trim().length > 0 || entryPreview != null || entryListWarnings.length > 0;
  const isDirty = currentSignature !== baselineSignature || hasAuxiliaryDraft;

  useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty, onDirtyChange]);

  function updateRequirement(index: number, patch: Partial<RequirementDraft>) {
    setRequirements((current) => current.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)));
  }

  function removeRequirement(index: number) {
    setRequirements((current) => current.filter((_, rowIndex) => rowIndex !== index));
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

  function selectedEntryPreviewMatch(row: ProjectRequirementPreviewRow): CatalogSearchResult | null {
    const fallbackSelection =
      !row.suggested_match || row.status === "needs_review" || row.status === "unresolved"
        ? null
        : projectPreviewMatchToCatalogResult(row.suggested_match);
    return resolvePreviewSelection(entryPreviewSelections, row.row, fallbackSelection);
  }

  async function previewEntryList() {
    if (!entryListText.trim()) return;
    setSaving(true);
    setMessage("");
    resetPreviewState();
    try {
      const preview = await apiSend<ProjectRequirementPreview>("/projects/requirements/preview", {
        method: "POST",
        body: JSON.stringify({ text: entryListText }),
      });
      applyEntryPreview(preview);
      setMessage(
        preview.can_auto_accept
          ? `Preview ready: ${preview.summary.total_rows} row(s) are ready to apply.`
          : `Preview ready: review=${preview.summary.needs_review}, unresolved=${preview.summary.unresolved}.`,
      );
    } catch (error) {
      setMessage(formatActionError("Preview failed", error));
    } finally {
      setSaving(false);
    }
  }

  function applyEntryPreviewToRequirements() {
    if (!entryPreview) return;
    const nextRequirements = entryPreview.rows.map((row) => {
      const selection = selectedEntryPreviewMatch(row);
      if (selection) {
        return {
          ...blankRequirementDraft(),
          target_type: "ITEM" as const,
          target_id: String(selection.entity_id),
          target_query: selection.display_label,
          quantity: row.quantity,
          match_status: "matched" as const,
        };
      }
      return {
        ...blankRequirementDraft(),
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
        .map((row) => row.message),
    );
    setMessage(`Applied ${entryPreview.rows.length} preview row(s) to requirements.`);
    resetPreviewState();
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    try {
      const payload = {
        name,
        status,
        planned_start: plannedStart.trim() || null,
        requirements: buildRequirementPayload(requirements),
      };
      if (isEditing) {
        await apiSend(`/projects/${projectId}`, {
          method: "PUT",
          body: JSON.stringify(payload),
        });
        setEntryListText("");
        setEntryListWarnings([]);
        resetPreviewState();
        setBaselineSignature(
          buildEditorSignature({
            name,
            status,
            plannedStart,
            requirements,
          }),
        );
        setMessage("Project saved.");
        await mutateProject();
        await onSaved?.(projectId);
      } else {
        const created = await apiSend<ProjectDetail>("/projects", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        resetToBlank();
        setMessage(`Created project #${created.project_id}.`);
        await onSaved?.(created.project_id);
      }
    } catch (error) {
      setMessage(formatActionError(isEditing ? "Save failed" : "Create failed", error));
    } finally {
      setSaving(false);
    }
  }

  const sectionTitle =
    title ?? (isEditing ? `Edit Project #${projectId ?? ""}` : "Create Project");

  return (
    <section className={surfaceClassName}>
      <h2 className="mb-3 font-display text-lg font-semibold">{sectionTitle}</h2>
      {projectError && <p className="mb-3 text-sm text-red-600">{String(projectError)}</p>}
      {isEditing && projectLoading && !projectData && (
        <p className="mb-3 text-sm text-slate-500">Loading project...</p>
      )}
      {(!isEditing || projectData) && (
        <form className="grid gap-3 md:grid-cols-3" onSubmit={handleSubmit}>
          <input
            data-autofocus={autoFocusField === "name" ? "true" : undefined}
            className="input"
            placeholder="Project name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
          />
          <select
            className="input"
            value={status}
            onChange={(event) => setStatus(event.target.value as ProjectStatus)}
          >
            <option value="PLANNING">PLANNING</option>
            <option value="CONFIRMED">CONFIRMED</option>
            <option value="ACTIVE">ACTIVE</option>
            <option value="COMPLETED">COMPLETED</option>
            <option value="CANCELLED">CANCELLED</option>
          </select>
          <input
            data-autofocus={autoFocusField === "planned_start" ? "true" : undefined}
            className="input"
            type="date"
            value={plannedStart}
            onChange={(event) => setPlannedStart(event.target.value)}
          />
          <div className="md:col-span-3">
            <div className="mb-3 rounded-md border border-slate-200 bg-slate-50 p-3">
              <p className="text-xs font-semibold text-slate-600">Quick item list input</p>
              <p className="mb-2 text-xs text-slate-500">Paste one line per item: item_number,quantity</p>
              <textarea
                className="input min-h-[88px]"
                placeholder={"LAS-001,2\nMIRROR-19,4"}
                value={entryListText}
                onChange={(event) => {
                  setEntryListText(event.target.value);
                  setMessage("");
                  resetPreviewState();
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
              {!!message && <p className="mt-2 text-xs text-slate-600">{message}</p>}
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
                                      setEntryPreviewSelections((current) => ({
                                        ...current,
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
                    <button className="button-subtle" type="button" onClick={resetPreviewState}>
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
                onClick={() => setRequirements((current) => [...current, blankRequirementDraft()])}
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
                  {requirements.map((row, index) => (
                    <tr key={index} className="border-b border-slate-100">
                      <td className="px-2 py-2">
                        <select
                          className="input"
                          value={row.target_type}
                          onChange={(event) =>
                            updateRequirement(index, {
                              target_type: event.target.value as RequirementDraft["target_type"],
                              target_id: "",
                              target_query: "",
                              match_status: undefined,
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
                              updateRequirement(index, {
                                target_id: value ? String(value.entity_id) : "",
                                target_query: value?.display_label ?? "",
                                match_status: value ? "matched" : undefined,
                              })
                            }
                            placeholder="Search items"
                            recentKey="project-requirement-item"
                            seedQuery={row.target_query}
                            value={selectedRequirementCatalogResult(row)}
                          />
                        ) : (
                          <CatalogPicker
                            allowedTypes={["assembly"]}
                            onChange={(value) =>
                              updateRequirement(index, {
                                target_id: value ? String(value.entity_id) : "",
                                target_query: value?.display_label ?? "",
                                match_status: value ? "matched" : undefined,
                              })
                            }
                            placeholder="Search assemblies"
                            recentKey="project-requirement-assembly"
                            seedQuery={row.target_query}
                            value={selectedRequirementCatalogResult(row)}
                          />
                        )}
                        {row.match_status === "unregistered" && (
                          <p className="mt-1 text-xs font-semibold text-amber-700">
                            No registered item matched.
                          </p>
                        )}
                        {onOpenItem && row.target_type === "ITEM" && row.target_id && (
                          <button
                            className="mt-2 button-subtle"
                            type="button"
                            onClick={() =>
                              onOpenItem(
                                Number(row.target_id),
                                itemCatalogById.get(Number(row.target_id))?.display_label ??
                                  `Item #${row.target_id}`,
                              )
                            }
                          >
                            Open Item
                          </button>
                        )}
                      </td>
                      <td className="px-2 py-2">
                        <input
                          className="input"
                          type="number"
                          min={1}
                          value={row.quantity}
                          onChange={(event) => updateRequirement(index, { quantity: event.target.value })}
                        />
                      </td>
                      <td className="px-2 py-2">
                        <select
                          className="input"
                          value={row.requirement_type}
                          onChange={(event) =>
                            updateRequirement(index, {
                              requirement_type: event.target.value as RequirementDraft["requirement_type"],
                            })
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
                          onChange={(event) => updateRequirement(index, { note: event.target.value })}
                        />
                      </td>
                      <td className="px-2 py-2">
                        <button className="button-subtle" type="button" onClick={() => removeRequirement(index)}>
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
            <button className="button" disabled={saving} type="submit">
              {submitLabel ?? (isEditing ? "Save Project" : "Create Project")}
            </button>
            {onCancel && (
              <button className="button-subtle" type="button" onClick={onCancel}>
                Cancel
              </button>
            )}
          </div>
        </form>
      )}
    </section>
  );
}
