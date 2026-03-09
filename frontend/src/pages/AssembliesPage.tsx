import { FormEvent, useMemo, useState } from "react";
import useSWR from "swr";
import { apiGetWithPagination, apiSend } from "../lib/api";
import { CatalogPicker } from "../components/CatalogPicker";
import type { CatalogSearchResult, Item } from "../lib/types";

type AssemblyRow = {
  assembly_id: number;
  name: string;
  description: string | null;
  component_count: number;
};

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

export function AssembliesPage() {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [components, setComponents] = useState<Array<{ item_id: string; quantity: string }>>([
    { item_id: "", quantity: "1" }
  ]);
  const [loading, setLoading] = useState(false);

  const { data, error, isLoading, mutate } = useSWR("/assemblies", () =>
    apiGetWithPagination<AssemblyRow[]>("/assemblies?per_page=200")
  );
  const { data: itemsResp } = useSWR("/items-options-assemblies", () =>
    apiGetWithPagination<Item[]>("/items?per_page=1000")
  );
  const items = itemsResp?.data ?? [];
  const itemCatalogById = useMemo(
    () => new Map(items.map((item) => [item.item_id, itemToCatalogResult(item)])),
    [items]
  );

  function updateComponent(index: number, patch: Partial<{ item_id: string; quantity: string }>) {
    setComponents((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function removeComponent(index: number) {
    setComponents((prev) => prev.filter((_, i) => i !== index));
  }

  async function createAssembly(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      const payloadComponents = components
        .filter((row) => row.item_id && Number(row.quantity) > 0)
        .map((row) => ({
          item_id: Number(row.item_id),
          quantity: Number(row.quantity)
        }));
      await apiSend("/assemblies", {
        method: "POST",
        body: JSON.stringify({
          name,
          description: description || null,
          components: payloadComponents
        })
      });
      setName("");
      setDescription("");
      setComponents([{ item_id: "", quantity: "1" }]);
      await mutate();
    } finally {
      setLoading(false);
    }
  }

  async function remove(assemblyId: number) {
    setLoading(true);
    try {
      await apiSend(`/assemblies/${assemblyId}`, { method: "DELETE", body: JSON.stringify({}) });
      await mutate();
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <section>
        <h1 className="font-display text-3xl font-bold">Assemblies</h1>
        <p className="mt-1 text-sm text-slate-600">
          Define reusable component groups and map them to locations.
        </p>
      </section>

      <section className="panel p-4">
        <h2 className="mb-3 font-display text-lg font-semibold">Create Assembly</h2>
        <form className="grid gap-3 md:grid-cols-3" onSubmit={createAssembly}>
          <input
            className="input"
            placeholder="Assembly name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <input
            className="input"
            placeholder="Description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
          <button className="button" disabled={loading} type="submit">
            Create
          </button>
          <div className="md:col-span-3">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-sm font-semibold text-slate-700">Components</p>
              <button
                className="button-subtle"
                type="button"
                onClick={() => setComponents((prev) => [...prev, { item_id: "", quantity: "1" }])}
              >
                Add Row
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="min-w-[640px] text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-slate-500">
                    <th className="px-2 py-2">Item</th>
                    <th className="px-2 py-2">Qty per assembly</th>
                    <th className="px-2 py-2">-</th>
                  </tr>
                </thead>
                <tbody>
                  {components.map((row, idx) => (
                    <tr key={idx} className="border-b border-slate-100">
                      <td className="px-2 py-2">
                        <CatalogPicker
                          allowedTypes={["item"]}
                          onChange={(value) =>
                            updateComponent(idx, { item_id: value ? String(value.entity_id) : "" })
                          }
                          placeholder="Search items"
                          recentKey="assembly-components"
                          value={row.item_id ? itemCatalogById.get(Number(row.item_id)) ?? null : null}
                        />
                      </td>
                      <td className="px-2 py-2">
                        <input
                          className="input"
                          type="number"
                          min={1}
                          value={row.quantity}
                          onChange={(e) => updateComponent(idx, { quantity: e.target.value })}
                        />
                      </td>
                      <td className="px-2 py-2">
                        <button className="button-subtle" type="button" onClick={() => removeComponent(idx)}>
                          Del
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </form>
      </section>

      <section className="panel p-4">
        <h2 className="mb-3 font-display text-lg font-semibold">Assembly List</h2>
        {isLoading && <p className="text-sm text-slate-500">Loading...</p>}
        {error && <p className="text-sm text-red-600">{String(error)}</p>}
        {data?.data && (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="px-2 py-2">ID</th>
                  <th className="px-2 py-2">Name</th>
                  <th className="px-2 py-2">Description</th>
                  <th className="px-2 py-2">Components</th>
                  <th className="px-2 py-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {data.data.map((row) => (
                  <tr key={row.assembly_id} className="border-b border-slate-100">
                    <td className="px-2 py-2">#{row.assembly_id}</td>
                    <td className="px-2 py-2 font-semibold">{row.name}</td>
                    <td className="px-2 py-2">{row.description ?? "-"}</td>
                    <td className="px-2 py-2">{row.component_count}</td>
                    <td className="px-2 py-2">
                      <button className="button-subtle" onClick={() => remove(row.assembly_id)}>
                        Delete
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
