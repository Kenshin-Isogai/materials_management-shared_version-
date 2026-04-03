import { useState } from "react";
import useSWR from "swr";
import { apiGet, apiSend } from "@/lib/api";

type LocationRow = {
  location: string;
  item_count: number;
  total_quantity: number;
};

type LocationDetail = {
  location: string;
  inventory: Array<{ item_number: string; quantity: number }>;
  assemblies: Array<{ assembly_name: string; quantity: number }>;
  advisory_components: Array<{ item_number: string; advisory_quantity: number }>;
};

export function LocationsPage() {
  const [selected, setSelected] = useState<string>("");
  const [assignmentsJson, setAssignmentsJson] = useState('[{"assembly_id":1,"quantity":1}]');
  const [busy, setBusy] = useState(false);

  const locations = useSWR("/locations", () => apiGet<LocationRow[]>("/locations"));
  const detail = useSWR(
    selected ? `/locations/${selected}` : null,
    () => apiGet<LocationDetail>(`/locations/${encodeURIComponent(selected)}`)
  );

  async function disassemble() {
    if (!selected) return;
    setBusy(true);
    try {
      await apiSend(`/locations/${encodeURIComponent(selected)}/disassemble`, {
        method: "POST",
        body: JSON.stringify({})
      });
      await Promise.all([locations.mutate(), detail.mutate()]);
    } finally {
      setBusy(false);
    }
  }

  async function applyAssignments() {
    if (!selected) return;
    setBusy(true);
    try {
      await apiSend(`/locations/${encodeURIComponent(selected)}/assemblies`, {
        method: "PUT",
        body: JSON.stringify({
          assignments: JSON.parse(assignmentsJson)
        })
      });
      await detail.mutate();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <section>
        <h1 className="font-display text-3xl font-bold">Location</h1>
        <p className="mt-1 text-sm text-slate-600">
          Inspect locations, adjust assembly assignments, and disassemble back to STOCK.
        </p>
      </section>

      <section className="panel p-4">
        <h2 className="mb-3 font-display text-lg font-semibold">Location List</h2>
        <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-4">
          {(locations.data ?? []).map((loc) => (
            <button
              key={loc.location}
              className={`rounded-xl border px-3 py-3 text-left transition ${
                selected === loc.location
                  ? "border-signal bg-signal/10"
                  : "border-slate-200 bg-white hover:border-slate-300"
              }`}
              onClick={() => setSelected(loc.location)}
            >
              <div className="font-semibold">{loc.location}</div>
              <div className="text-xs text-slate-500">
                {loc.item_count} items / {loc.total_quantity} qty
              </div>
            </button>
          ))}
        </div>
      </section>

      {selected && (
        <section className="grid gap-5 lg:grid-cols-2">
          <div className="panel p-4">
            <h2 className="font-display text-lg font-semibold">
              Location Detail: <span className="text-signal">{selected}</span>
            </h2>
            {!detail.data && <p className="mt-3 text-sm text-slate-500">Loading...</p>}
            {detail.data && (
              <div className="mt-4 space-y-4 text-sm">
                <div>
                  <p className="mb-2 font-semibold">Inventory</p>
                  <ul className="space-y-1">
                    {detail.data.inventory.map((row, idx) => (
                      <li key={idx} className="rounded-lg bg-slate-50 px-3 py-2">
                        {row.item_number}: {row.quantity}
                      </li>
                    ))}
                    {!detail.data.inventory.length && <li className="text-slate-400">None</li>}
                  </ul>
                </div>
                <div>
                  <p className="mb-2 font-semibold">Assemblies</p>
                  <ul className="space-y-1">
                    {detail.data.assemblies.map((row, idx) => (
                      <li key={idx} className="rounded-lg bg-slate-50 px-3 py-2">
                        {row.assembly_name}: {row.quantity}
                      </li>
                    ))}
                    {!detail.data.assemblies.length && <li className="text-slate-400">None</li>}
                  </ul>
                </div>
              </div>
            )}
            <button className="button mt-4" disabled={busy} onClick={disassemble}>
              Disassemble To STOCK
            </button>
          </div>

          <div className="panel p-4">
            <h2 className="font-display text-lg font-semibold">Set Assembly Usage</h2>
            <p className="mt-2 text-xs text-slate-500">
              JSON format: <code>[{"{"}"assembly_id":1,"quantity":2{"}"}]</code>
            </p>
            <textarea
              className="input mt-3 min-h-56 font-mono text-xs"
              value={assignmentsJson}
              onChange={(e) => setAssignmentsJson(e.target.value)}
            />
            <button className="button mt-3" disabled={busy} onClick={applyAssignments}>
              Save Assignments
            </button>
          </div>
        </section>
      )}
    </div>
  );
}

