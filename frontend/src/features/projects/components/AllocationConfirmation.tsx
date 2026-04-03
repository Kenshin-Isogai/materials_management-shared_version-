import { cn } from "@/lib/utils";
import type { ConfirmAllocationResult } from "@/lib/types";

function formatDate(value: string | null | undefined): string {
  return value && value.trim() ? value : "-";
}

export function AllocationConfirmation({
  preview,
  onClear,
}: {
  preview: ConfirmAllocationResult | null;
  onClear: () => void;
}) {
  if (!preview) return null;

  return (
    <div className="mb-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-semibold">
            Allocation Preview
            {preview.dry_run ? "" : " Result"}
          </p>
          <p className="text-xs text-slate-500">
            Target date {formatDate(preview.target_date)} | Orders assigned{" "}
            {preview.orders_assigned.length} | Orders split{" "}
            {preview.orders_split.length} | Reservations{" "}
            {preview.reservations_created.length}
          </p>
        </div>
        {!preview.dry_run && (
          <button className="button-subtle" type="button" onClick={onClear}>
            Clear
          </button>
        )}
      </div>
      <div className="mt-3 grid gap-3 xl:grid-cols-2">
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Orders
          </p>
          <div className="space-y-2">
            {preview.orders_assigned.map((entry) => (
              <p key={`assign-${entry.order_id}-${entry.item_id}`}>
                Assign order #{entry.order_id} item #{entry.item_id} qty{" "}
                {entry.quantity}.
              </p>
            ))}
            {preview.orders_split.map((entry) => (
              <p key={`split-${entry.original_order_id}-${entry.item_id}`}>
                Split order #{entry.original_order_id}: assign{" "}
                {entry.assigned_quantity}, leave {entry.remaining_quantity}
                {entry.new_order_id
                  ? `, created #${entry.new_order_id}`
                  : ""}
                .
              </p>
            ))}
            {!preview.orders_assigned.length &&
              !preview.orders_split.length && (
                <p className="text-slate-500">
                  No generic orders will be dedicated.
                </p>
              )}
          </div>
        </div>
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Reservations
          </p>
          <div className="space-y-2">
            {preview.reservations_created.map((entry) => (
              <p
                key={`reservation-${entry.item_id}-${entry.reservation_id ?? "preview"}`}
              >
                Reserve item #{entry.item_id} qty {entry.quantity}
                {entry.reservation_id
                  ? ` as reservation #${entry.reservation_id}`
                  : ""}
                .
              </p>
            ))}
            {!preview.reservations_created.length && (
              <p className="text-slate-500">
                No stock-backed reservations will be created.
              </p>
            )}
          </div>
        </div>
      </div>
      {!!preview.skipped.length && (
        <div className="mt-3">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Skipped
          </p>
          <div className="space-y-1">
            {preview.skipped.map((entry, index) => (
              <p
                key={`skipped-${entry.item_id}-${index}`}
                className="text-slate-600"
              >
                Item #{entry.item_id}
                {entry.order_id ? ` / order #${entry.order_id}` : ""}:{" "}
                {entry.reason}
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
