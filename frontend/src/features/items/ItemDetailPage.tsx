import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import useSWR from "swr";
import { cn } from "@/lib/utils";
import { StatusCallout } from "@/components/StatusCallout";
import { apiGet, apiGetWithPagination } from "@/lib/api";
import {
  isAuthError,
  isBackendUnavailableError,
  presentApiError,
} from "@/lib/errorUtils";
import type {
  InventoryRow,
  Item,
  ItemFlowTimeline,
  ItemPlanningContext,
  Order,
  PlanningSource,
  Reservation,
} from "@/lib/types";

type ReservationRow = Reservation & {
  project_id: number | null;
  project_name?: string | null;
};

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

function formatDate(value: string | null | undefined): string {
  return value && value.trim() ? value : "-";
}

function normalizePlanningDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (trimmed.toLowerCase() === "none" || trimmed.toLowerCase() === "null")
    return null;
  return trimmed;
}

function formatPlanningDate(value: string | null | undefined): string {
  return formatDate(normalizePlanningDate(value));
}

function describePlanningDate(value: string | null | undefined): string {
  const normalized = normalizePlanningDate(value);
  return normalized ? formatDate(normalized) : "unknown date";
}

function sourceTone(sourceType: PlanningSource["source_type"]): string {
  switch (sourceType) {
    case "stock":
      return "bg-slate-100 text-slate-700";
    case "generic_order":
      return "bg-sky-100 text-sky-800";
    case "dedicated_order":
      return "bg-emerald-100 text-emerald-800";
    case "quoted_rfq":
      return "bg-amber-100 text-amber-800";
    default:
      return "bg-slate-100 text-slate-700";
  }
}

function comparePlanningSourceDate(a: PlanningSource, b: PlanningSource): number {
  const left = normalizePlanningDate(a.date) ?? "9999-12-31";
  const right = normalizePlanningDate(b.date) ?? "9999-12-31";
  if (left !== right) return left.localeCompare(right);
  const leftRef = a.ref_id ?? Number.MAX_SAFE_INTEGER;
  const rightRef = b.ref_id ?? Number.MAX_SAFE_INTEGER;
  if (leftRef !== rightRef) return leftRef - rightRef;
  return a.label.localeCompare(b.label);
}

type RecoveryBurndownStep = {
  date: string | null;
  quantity: number;
  label: string;
  sourceType: PlanningSource["source_type"];
  remainingAfter: number;
};

function buildRecoveryBurndown(
  shortageAtStart: number,
  recoverySources: PlanningSource[],
): RecoveryBurndownStep[] {
  let remaining = shortageAtStart;
  return [...recoverySources]
    .sort(comparePlanningSourceDate)
    .filter((source) => source.quantity > 0)
    .map((source) => {
      remaining = Math.max(0, remaining - source.quantity);
      return {
        date: normalizePlanningDate(source.date),
        quantity: source.quantity,
        label: source.label,
        sourceType: source.source_type,
        remainingAfter: remaining,
      };
    });
}

function recoverySummaryText(
  shortageAtStart: number,
  recoverySources: PlanningSource[],
): string {
  if (shortageAtStart <= 0) return "No start-date gap.";
  const steps = buildRecoveryBurndown(shortageAtStart, recoverySources);
  if (!steps.length) return "No later recovery scheduled.";
  const recovered = Math.min(
    shortageAtStart,
    steps.reduce((total, step) => total + step.quantity, 0),
  );
  const resolvedStep = steps.find((step) => step.remainingAfter === 0);
  if (resolvedStep) {
    return `Recovered ${recovered} by ${describePlanningDate(resolvedStep.date)}. Resolved on ${describePlanningDate(resolvedStep.date)}.`;
  }
  const lastStep = steps[steps.length - 1];
  return `Recovered ${recovered} by ${describePlanningDate(lastStep?.date)}. Still short ${steps[steps.length - 1]?.remainingAfter ?? shortageAtStart}.`;
}

function PlanningSourceList({
  title,
  sources,
  emptyLabel,
}: {
  title: string;
  sources: PlanningSource[];
  emptyLabel: string;
}) {
  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </p>
      {sources.length ? (
        <div className="flex flex-wrap gap-2">
          {sources.map((source, index) => (
            <span
              key={`${source.source_type}-${source.ref_id ?? "stock"}-${index}`}
              className={cn(
                "inline-flex items-center gap-2 rounded-full px-2 py-1 text-xs font-medium",
                sourceTone(source.source_type),
              )}
              title={normalizePlanningDate(source.date) ?? undefined}
            >
              <span>{source.quantity}</span>
              <span>{source.label}</span>
            </span>
          ))}
        </div>
      ) : (
        <p className="text-xs text-slate-500">{emptyLabel}</p>
      )}
    </div>
  );
}

function RecoveryBurndownList({
  shortageAtStart,
  recoverySources,
}: {
  shortageAtStart: number;
  recoverySources: PlanningSource[];
}) {
  const steps = buildRecoveryBurndown(shortageAtStart, recoverySources);
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Recovery Burndown
        </p>
        <p className="text-xs text-slate-500">
          {recoverySummaryText(shortageAtStart, recoverySources)}
        </p>
      </div>
      {steps.length ? (
        <div className="overflow-x-auto rounded-2xl border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-left text-slate-500">
              <tr>
                <th className="px-3 py-2">Date</th>
                <th className="px-3 py-2">Recovery</th>
                <th className="px-3 py-2">Source</th>
                <th className="px-3 py-2">Gap After</th>
              </tr>
            </thead>
            <tbody>
              {steps.map((step, index) => (
                <tr
                  key={`${step.date ?? "unknown"}-${step.label}-${index}`}
                  className="border-t border-slate-200"
                >
                  <td className="px-3 py-2">
                    {formatPlanningDate(step.date)}
                  </td>
                  <td className="px-3 py-2 font-semibold text-sky-800">
                    +{step.quantity}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={cn(
                        "inline-flex items-center rounded-full px-2 py-1 text-xs font-medium",
                        sourceTone(step.sourceType),
                      )}
                    >
                      {step.label}
                    </span>
                  </td>
                  <td className="px-3 py-2 font-semibold">
                    {step.remainingAfter === 0
                      ? "Fully resolved"
                      : `${step.remainingAfter} remaining`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="rounded-2xl border border-dashed border-slate-300 px-4 py-4 text-sm text-slate-500">
          No later recovery source recorded yet.
        </p>
      )}
    </div>
  );
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

export function ItemDetailPage() {
  const { itemId: itemIdParam } = useParams<{ itemId: string }>();
  const itemId = Number(itemIdParam);

  const { data: itemData, error: itemError } = useSWR(
    `/items/${itemId}`,
    () => apiGet<Item>(`/items/${itemId}`),
  );
  const { data: inventoryResp } = useSWR(
    `/workspace-item-inventory-${itemId}`,
    () =>
      apiGetWithPagination<InventoryRow[]>(
        `/inventory?item_id=${itemId}&per_page=200`,
      ),
  );
  const { data: flowData } = useSWR(`/items/${itemId}/flow`, () =>
    apiGet<ItemFlowTimeline>(`/items/${itemId}/flow`),
  );
  const { data: reservationsResp } = useSWR(
    `/workspace-item-reservations-${itemId}`,
    () =>
      apiGetWithPagination<ReservationRow[]>(
        `/reservations?item_id=${itemId}&status=ACTIVE&per_page=200`,
      ),
  );
  const ordersPath = `/purchase-order-lines?item_id=${itemId}&include_arrived=false&per_page=200`;
  const { data: ordersResp } = useSWR(ordersPath, () =>
    apiGetWithPagination<Order[]>(ordersPath),
  );
  const planningPath = useMemo(() => {
    return `/items/${itemId}/planning-context`;
  }, [itemId]);
  const { data: planningData } = useSWR(planningPath, () =>
    apiGet<ItemPlanningContext>(planningPath),
  );

  const inventoryRows = inventoryResp?.data ?? [];
  const reservations = reservationsResp?.data ?? [];
  const orders = ordersResp?.data ?? [];

  if (itemError) {
    return (
      <div className="space-y-5">
        {renderWorkspaceError(itemError, "item context")}
      </div>
    );
  }

  if (!itemData) {
    return (
      <div className="space-y-5">
        <p className="text-sm text-slate-500">Loading item context...</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <section className="space-y-2">
        <h2 className="font-display text-2xl font-semibold">
          {itemData.item_number}
        </h2>
        <p className="text-sm text-slate-600">
          {itemData.manufacturer_name} | Category {itemData.category ?? "-"}
        </p>
        {itemData.description && (
          <p className="text-sm text-slate-600">{itemData.description}</p>
        )}
        <div className="flex flex-wrap gap-2 text-sm">
          <Link className="button-subtle" to="/items">
            Open Items Page
          </Link>
          <Link className="button-subtle" to="/purchase-order-lines">
            Open Purchase Orders Page
          </Link>
        </div>
      </section>

      <section className="grid gap-3 md:grid-cols-4">
        <SummaryMetric
          label="Current Stock"
          value={flowData?.current_stock ?? 0}
          tone="emerald"
        />
        <SummaryMetric label="Locations" value={inventoryRows.length} />
        <SummaryMetric
          label="Open PO Lines"
          value={orders.length}
          tone="sky"
        />
        <SummaryMetric
          label="Active Reservations"
          value={reservations.length}
          tone="amber"
        />
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="font-display text-lg font-semibold">
              Planning Allocation Context
            </h3>
            <p className="text-sm text-slate-600">
              Cross-project demand and coverage for this item at target date{" "}
              {formatDate(planningData?.target_date)}.
            </p>
          </div>
          {planningData?.preview_project_id != null && (
            <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800">
              Includes Preview Project #{planningData.preview_project_id}
            </span>
          )}
        </div>
        <div className="space-y-3">
          {(planningData?.projects ?? []).map((project) => (
            <div
              key={`${project.project_id}-${project.is_planning_preview ? "preview" : "committed"}`}
              className={cn(
                "rounded-2xl border px-4 py-4",
                project.is_planning_preview
                  ? "border-amber-300 bg-amber-50"
                  : "border-slate-200",
              )}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="font-semibold">{project.project_name}</p>
                    <span
                      className={cn(
                        "rounded-full px-2 py-1 text-xs font-semibold",
                        statusTone(project.project_status),
                      )}
                    >
                      {project.project_status}
                    </span>
                    {project.is_planning_preview && (
                      <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-800">
                        Preview
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-slate-600">
                    Start {formatDate(project.planned_start)}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Link
                    className="button-subtle"
                    to={`/projects/${project.project_id}`}
                  >
                    Project
                  </Link>
                  <Link className="button-subtle" to="/procurement">
                    RFQ
                  </Link>
                </div>
              </div>
              <div className="mt-4 grid gap-3 lg:grid-cols-5">
                <div className="rounded-xl border border-slate-200 bg-white px-3 py-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Required
                  </p>
                  <p className="mt-1 text-xl font-bold">
                    {project.required_quantity}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-white px-3 py-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Covered By Start
                  </p>
                  <p className="mt-1 text-xl font-bold">
                    {project.covered_on_time_quantity}
                  </p>
                  <p className="text-xs text-slate-500">
                    Dedicated {project.dedicated_supply_by_start} | Generic{" "}
                    {project.generic_allocated_quantity} / pool{" "}
                    {project.generic_available_at_start}
                  </p>
                </div>
                <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">
                    On-Time Gap
                  </p>
                  <p className="mt-1 text-xl font-bold text-amber-900">
                    {project.shortage_at_start}
                  </p>
                </div>
                <div className="rounded-xl border border-sky-200 bg-sky-50 px-3 py-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-sky-700">
                    Recovered Later
                  </p>
                  <p className="mt-1 text-xl font-bold text-sky-900">
                    {project.recovered_after_start_quantity}
                  </p>
                  <p className="text-xs text-sky-700">
                    Generic {project.future_generic_recovery_quantity} |
                    Dedicated {project.future_dedicated_recovery_quantity}
                  </p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Remaining
                  </p>
                  <p className="mt-1 text-xl font-bold">
                    {project.remaining_shortage_quantity}
                  </p>
                </div>
              </div>
              <div className="mt-4 grid gap-3 lg:grid-cols-2">
                <PlanningSourceList
                  title="Coverage Sources"
                  sources={project.supply_sources_by_start}
                  emptyLabel="No coverage source recorded by start."
                />
                <PlanningSourceList
                  title="Recovery Sources"
                  sources={project.recovery_sources_after_start}
                  emptyLabel="No recovery source recorded after start."
                />
              </div>
              <RecoveryBurndownList
                shortageAtStart={project.shortage_at_start}
                recoverySources={project.recovery_sources_after_start}
              />
            </div>
          ))}
          {!planningData?.projects.length && (
            <p className="rounded-2xl border border-dashed border-slate-300 px-4 py-5 text-sm text-slate-500">
              No committed or previewed project allocation context for this
              item.
            </p>
          )}
        </div>
      </section>

      <section className="space-y-3">
        <h3 className="font-display text-lg font-semibold">
          Incoming Purchase Order Lines
        </h3>
        <div className="space-y-2">
          {orders.map((order) => (
            <div
              key={order.order_id}
              className="rounded-2xl border border-slate-200 px-4 py-3"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="font-semibold">
                    PO Line #{order.order_id} | Qty {order.order_amount}
                  </p>
                  <p className="text-sm text-slate-600">
                    {order.supplier_name} | ETA{" "}
                    {formatDate(order.expected_arrival)} | {order.status}
                  </p>
                  <p className="text-xs text-slate-500">
                    {order.quotation_number}
                    {order.project_name ? ` | ${order.project_name}` : ""}
                  </p>
                </div>
              </div>
            </div>
          ))}
          {!orders.length && (
            <p className="rounded-2xl border border-dashed border-slate-300 px-4 py-5 text-sm text-slate-500">
              No open purchase order lines for this item.
            </p>
          )}
        </div>
      </section>

      <section className="space-y-3">
        <h3 className="font-display text-lg font-semibold">
          Active Project Demand
        </h3>
        <div className="space-y-2">
          {reservations.map((reservation) => (
            <div
              key={reservation.reservation_id}
              className="rounded-2xl border border-slate-200 px-4 py-3"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="font-semibold">
                    Reservation #{reservation.reservation_id} | Qty{" "}
                    {reservation.quantity}
                  </p>
                  <p className="text-sm text-slate-600">
                    Deadline {formatDate(reservation.deadline)} |{" "}
                    {reservation.purpose ?? "No purpose"}
                  </p>
                  <p className="text-xs text-slate-500">
                    {reservation.project_name ?? "No linked project"}
                  </p>
                </div>
                {reservation.project_id && (
                  <Link
                    className="button-subtle"
                    to={`/projects/${reservation.project_id}`}
                  >
                    Open Project
                  </Link>
                )}
              </div>
            </div>
          ))}
          {!reservations.length && (
            <p className="rounded-2xl border border-dashed border-slate-300 px-4 py-5 text-sm text-slate-500">
              No active reservations for this item.
            </p>
          )}
        </div>
      </section>

      <section className="space-y-3">
        <h3 className="font-display text-lg font-semibold">
          Inventory By Location
        </h3>
        <div className="space-y-2">
          {inventoryRows.map((row) => (
            <div
              key={`${row.ledger_id}-${row.location}`}
              className="rounded-2xl border border-slate-200 px-4 py-3"
            >
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="font-semibold">{row.location}</p>
                  <p className="text-sm text-slate-500">
                    Last updated {formatDate(row.last_updated)}
                  </p>
                </div>
                <p className="text-xl font-bold">{row.quantity}</p>
              </div>
            </div>
          ))}
          {!inventoryRows.length && (
            <p className="rounded-2xl border border-dashed border-slate-300 px-4 py-5 text-sm text-slate-500">
              No inventory rows for this item.
            </p>
          )}
        </div>
      </section>

      <section className="space-y-3">
        <h3 className="font-display text-lg font-semibold">Flow Timeline</h3>
        <div className="space-y-2">
          {(flowData?.events ?? []).map((event) => (
            <div
              key={`${event.event_at}-${event.source_ref}`}
              className="rounded-2xl border border-slate-200 px-4 py-3"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="font-semibold">{event.reason}</p>
                  <p className="text-sm text-slate-600">
                    {event.event_at} | {event.source_ref}
                  </p>
                  {event.note && (
                    <p className="text-xs text-slate-500">{event.note}</p>
                  )}
                </div>
                <div
                  className={cn(
                    "rounded-full px-3 py-1 text-sm font-semibold",
                    event.delta >= 0
                      ? "bg-emerald-100 text-emerald-800"
                      : "bg-amber-100 text-amber-800",
                  )}
                >
                  {event.delta >= 0 ? "+" : ""}
                  {event.delta}
                </div>
              </div>
            </div>
          ))}
          {!flowData?.events.length && (
            <p className="rounded-2xl border border-dashed border-slate-300 px-4 py-5 text-sm text-slate-500">
              No flow events available.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
