import { FormEvent, useState } from "react";
import useSWR from "swr";
import { apiGet, apiSend } from "@/lib/api";

type Manufacturer = { manufacturer_id: number; name: string };
type Supplier = { supplier_id: number; name: string };
type CategoryAlias = {
  alias_category: string;
  canonical_category: string;
  updated_at: string;
};

export function MasterPage() {
  const [manufacturerName, setManufacturerName] = useState("");
  const [supplierName, setSupplierName] = useState("");
  const [aliasCategory, setAliasCategory] = useState("");
  const [canonicalCategory, setCanonicalCategory] = useState("");
  const [busy, setBusy] = useState(false);

  const manufacturers = useSWR("/manufacturers", () => apiGet<Manufacturer[]>("/manufacturers"));
  const suppliers = useSWR("/suppliers", () => apiGet<Supplier[]>("/suppliers"));
  const aliases = useSWR("/categories/aliases", () =>
    apiGet<CategoryAlias[]>("/categories/aliases")
  );

  async function createManufacturer(event: FormEvent) {
    event.preventDefault();
    if (!manufacturerName.trim()) return;
    setBusy(true);
    try {
      await apiSend("/manufacturers", {
        method: "POST",
        body: JSON.stringify({ name: manufacturerName.trim() })
      });
      setManufacturerName("");
      await manufacturers.mutate();
    } finally {
      setBusy(false);
    }
  }

  async function createSupplier(event: FormEvent) {
    event.preventDefault();
    if (!supplierName.trim()) return;
    setBusy(true);
    try {
      await apiSend("/suppliers", {
        method: "POST",
        body: JSON.stringify({ name: supplierName.trim() })
      });
      setSupplierName("");
      await suppliers.mutate();
    } finally {
      setBusy(false);
    }
  }

  async function mergeCategory(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await apiSend("/categories/merge", {
        method: "POST",
        body: JSON.stringify({
          alias_category: aliasCategory.trim(),
          canonical_category: canonicalCategory.trim()
        })
      });
      setAliasCategory("");
      setCanonicalCategory("");
      await aliases.mutate();
    } finally {
      setBusy(false);
    }
  }

  async function removeAlias(alias: string) {
    setBusy(true);
    try {
      await apiSend(`/categories/aliases/${encodeURIComponent(alias)}`, {
        method: "DELETE",
        body: JSON.stringify({})
      });
      await aliases.mutate();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <section>
        <h1 className="font-display text-3xl font-bold">Master Data</h1>
        <p className="mt-1 text-sm text-slate-600">
          Manage manufacturers, suppliers, and category soft-merge aliases.
        </p>
      </section>

      <section className="grid gap-5 lg:grid-cols-2">
        <form className="panel space-y-3 p-4" onSubmit={createManufacturer}>
          <h2 className="font-display text-lg font-semibold">Manufacturers</h2>
          <div className="flex gap-2">
            <input
              className="input"
              placeholder="Manufacturer name"
              value={manufacturerName}
              onChange={(e) => setManufacturerName(e.target.value)}
            />
            <button className="button" disabled={busy} type="submit">
              Add
            </button>
          </div>
          <ul className="max-h-64 space-y-1 overflow-auto text-sm">
            {(manufacturers.data ?? []).map((m) => (
              <li key={m.manufacturer_id} className="rounded-lg bg-slate-50 px-3 py-2">
                {m.name}
              </li>
            ))}
          </ul>
        </form>

        <form className="panel space-y-3 p-4" onSubmit={createSupplier}>
          <h2 className="font-display text-lg font-semibold">Suppliers</h2>
          <div className="flex gap-2">
            <input
              className="input"
              placeholder="Supplier name"
              value={supplierName}
              onChange={(e) => setSupplierName(e.target.value)}
            />
            <button className="button" disabled={busy} type="submit">
              Add
            </button>
          </div>
          <ul className="max-h-64 space-y-1 overflow-auto text-sm">
            {(suppliers.data ?? []).map((s) => (
              <li key={s.supplier_id} className="rounded-lg bg-slate-50 px-3 py-2">
                {s.name}
              </li>
            ))}
          </ul>
        </form>
      </section>

      <section className="panel space-y-3 p-4">
        <h2 className="font-display text-lg font-semibold">Category Soft Merge</h2>
        <form className="grid gap-3 md:grid-cols-3" onSubmit={mergeCategory}>
          <input
            className="input"
            placeholder="Alias category"
            value={aliasCategory}
            onChange={(e) => setAliasCategory(e.target.value)}
            required
          />
          <input
            className="input"
            placeholder="Canonical category"
            value={canonicalCategory}
            onChange={(e) => setCanonicalCategory(e.target.value)}
            required
          />
          <button className="button" disabled={busy} type="submit">
            Merge
          </button>
        </form>
        <ul className="space-y-2 text-sm">
          {(aliases.data ?? []).map((row) => (
            <li
              key={row.alias_category}
              className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2"
            >
              <span>
                {row.alias_category} → {row.canonical_category}
              </span>
              <button
                className="button-subtle"
                disabled={busy}
                onClick={() => removeAlias(row.alias_category)}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

