import { FormEvent, useMemo, useState } from "react";
import useSWR from "swr";
import { apiGetWithPagination, apiSend } from "../lib/api";
import type { Item } from "../lib/types";

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

const blankRequirement = (): RequirementRow => ({
  target_type: "ITEM",
  target_id: "",
  quantity: "1",
  requirement_type: "INITIAL",
  note: "",
  target_query: "",
  match_status: undefined
});

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
  const itemLookupByNumber = useMemo(() => {
    const lookup = new Map<string, Item[]>();
    for (const item of items) {
      const key = item.item_number.trim().toLowerCase();
      const current = lookup.get(key) ?? [];
      current.push(item);
      lookup.set(key, current);
    }
    return lookup;
  }, [items]);
  const itemIds = useMemo(() => new Set(items.map((item) => item.item_id)), [items]);
  const assemblyIds = useMemo(() => new Set(assemblies.map((assembly) => assembly.assembly_id)), [assemblies]);

  const itemSearchOptions = useMemo(
    () =>
      items.map((item) => ({
        value: `${item.item_number} #${item.item_id}`,
        item
      })),
    [items]
  );

  function itemLabel(item: Item) {
    return `${item.item_number} (${item.manufacturer_name}) #${item.item_id}`;
  }

  function updateRequirement(index: number, patch: Partial<RequirementRow>) {
    setRequirements((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function updateRequirementTargetFromText(index: number, targetType: RequirementRow["target_type"], text: string) {
    const parsedId = Number((text.split("#").pop() ?? "").trim());
    const isKnownTarget =
      targetType === "ITEM" ? itemIds.has(parsedId) : assemblyIds.has(parsedId);
    if (!Number.isNaN(parsedId) && parsedId > 0 && isKnownTarget) {
      updateRequirement(index, {
        target_type: targetType,
        target_id: String(parsedId),
        target_query: text,
        match_status: "matched"
      });
      return;
    }
    updateRequirement(index, {
      target_type: targetType,
      target_id: "",
      target_query: text,
      match_status: text.trim() ? "unregistered" : undefined
    });
  }

  function removeRequirement(index: number) {
    setRequirements((prev) => prev.filter((_, i) => i !== index));
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
      await mutate();
    } finally {
      setLoading(false);
    }
  }

  function parseEntryList() {
    const warnings: string[] = [];
    const parsedRows = entryListText
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [itemNumberRaw, quantityRaw] = line.split(",").map((part) => part.trim());
        const quantity = Number(quantityRaw || "1");
        const matchedItems = itemLookupByNumber.get(itemNumberRaw.toLowerCase()) ?? [];
        if (matchedItems.length === 0) {
          warnings.push(`Unregistered item: ${itemNumberRaw}`);
          return {
            ...blankRequirement(),
            target_type: "ITEM" as const,
            target_query: itemNumberRaw,
            quantity: String(Number.isFinite(quantity) && quantity > 0 ? quantity : 1),
            match_status: "unregistered" as const
          };
        }
        if (matchedItems.length > 1) {
          warnings.push(`Ambiguous item number (multiple manufacturers): ${itemNumberRaw}`);
          return {
            ...blankRequirement(),
            target_type: "ITEM" as const,
            target_query: itemNumberRaw,
            quantity: String(Number.isFinite(quantity) && quantity > 0 ? quantity : 1),
            match_status: "unregistered" as const
          };
        }
        const matchedItem = matchedItems[0];
        return {
          ...blankRequirement(),
          target_type: "ITEM" as const,
          target_id: String(matchedItem.item_id),
          target_query: `${matchedItem.item_number} #${matchedItem.item_id}`,
          quantity: String(Number.isFinite(quantity) && quantity > 0 ? quantity : 1),
          match_status: "matched" as const
        };
      });

    if (parsedRows.length > 0) {
      setRequirements(parsedRows);
    }
    setEntryListWarnings(warnings);
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
          Use <span className="font-semibold">Reservations</span> to allocate concrete quantities when work is ready to run.
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
                onChange={(e) => setEntryListText(e.target.value)}
              />
              <div className="mt-2 flex items-center gap-2">
                <button className="button-subtle" type="button" onClick={parseEntryList}>
                  Parse into rows
                </button>
                {!!entryListWarnings.length && (
                  <span className="text-xs font-semibold text-amber-700">
                    {entryListWarnings.length} unregistered item(s)
                  </span>
                )}
              </div>
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
              <table className="min-w-[980px] text-sm">
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
                              target_id: ""
                            })
                          }
                        >
                          <option value="ITEM">ITEM</option>
                          <option value="ASSEMBLY">ASSEMBLY</option>
                        </select>
                      </td>
                      <td className="px-2 py-2">
                        {row.target_type === "ITEM" ? (
                          <>
                            <input
                              className="input"
                              list="project-item-options"
                              placeholder="Search item_number and pick suggestion"
                              value={row.target_query}
                              onChange={(e) => updateRequirementTargetFromText(idx, "ITEM", e.target.value)}
                            />
                            <datalist id="project-item-options">
                              {itemSearchOptions.map((option) => (
                                <option key={option.item.item_id} value={option.value}>
                                  {itemLabel(option.item)}
                                </option>
                              ))}
                            </datalist>
                          </>
                        ) : (
                          <select
                            className="input"
                            value={row.target_id}
                            onChange={(e) => updateRequirement(idx, { target_id: e.target.value })}
                          >
                            <option value="">Select assembly</option>
                            {assemblies.map((assembly) => (
                              <option key={assembly.assembly_id} value={assembly.assembly_id}>
                                {assembly.name} #{assembly.assembly_id}
                              </option>
                            ))}
                          </select>
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
