import { useEffect, useMemo, useState } from "react";
import {
  Link,
  unstable_usePrompt as usePrompt,
  useBeforeUnload,
} from "react-router-dom";
import useSWR from "swr";
import { ProjectEditor } from "../components/ProjectEditor";
import { RfqBatchEditor } from "../components/RfqBatchEditor";
import { WorkspaceDrawer } from "../components/WorkspaceDrawer";
import { apiDownload, apiGet, apiGetWithPagination, apiSend } from "../lib/api";
import { nextSynchronizedBoardDate, resolveDrawerStackPush } from "../lib/workspaceState";
import type {
  InventoryRow,
  Item,
  ItemFlowTimeline,
  ItemPlanningContext,
  Order,
  PlanningAnalysisResult,
  PlanningAnalysisRow,
  PlanningSource,
  ProjectDetail,
  Reservation,
  WorkspaceProjectSummary,
  WorkspaceSummary,
} from "../lib/types";

type WorkspaceView = "summary" | "pipeline" | "board";

type ReservationRow = Reservation & {
  project_id: number | null;
  project_name?: string | null;
};

type DrawerContext =
  | {
      key: string;
      type: "project";
      label: string;
      projectId: number;
    }
  | {
      key: string;
      type: "item";
      label: string;
      itemId: number;
    }
  | {
      key: string;
      type: "rfq";
      label: string;
      projectId: number;
      itemId: number | null;
    };

const EMPTY_RFQ_SUMMARY: WorkspaceProjectSummary["rfq_summary"] = {
  total_batches: 0,
  open_batch_count: 0,
  closed_batch_count: 0,
  cancelled_batch_count: 0,
  draft_line_count: 0,
  sent_line_count: 0,
  quoted_line_count: 0,
  ordered_line_count: 0,
  latest_target_date: null,
};

function cx(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

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

function summaryTone(mode: WorkspaceProjectSummary["summary_mode"]): string {
  switch (mode) {
    case "authoritative":
      return "border-emerald-200 bg-emerald-50 text-emerald-800";
    case "preview_required":
      return "border-amber-200 bg-amber-50 text-amber-800";
    default:
      return "border-slate-200 bg-slate-50 text-slate-700";
  }
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

function formatDate(value: string | null | undefined): string {
  return value && value.trim() ? value : "-";
}

function pickDefaultProject(projects: WorkspaceProjectSummary[]): WorkspaceProjectSummary | null {
  return (
    projects.find((project) => project.status !== "COMPLETED" && project.status !== "CANCELLED") ??
    projects[0] ??
    null
  );
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
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</p>
      {sources.length ? (
        <div className="flex flex-wrap gap-2">
          {sources.map((source, index) => (
            <span
              key={`${source.source_type}-${source.ref_id ?? "stock"}-${index}`}
              className={cx(
                "inline-flex items-center gap-2 rounded-full px-2 py-1 text-xs font-medium",
                sourceTone(source.source_type),
              )}
              title={source.date ?? undefined}
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
    <div className={cx("rounded-2xl border px-4 py-3", toneClass)}>
      <p className="text-xs font-semibold uppercase tracking-wide opacity-70">{label}</p>
      <p className="mt-1 text-2xl font-bold">{value}</p>
    </div>
  );
}

function ProjectSummaryCard({
  project,
  selected,
  onOpenProject,
  onOpenBoard,
  onOpenRfq,
}: {
  project: WorkspaceProjectSummary;
  selected: boolean;
  onOpenProject: () => void;
  onOpenBoard: () => void;
  onOpenRfq: () => void;
}) {
  const planningSummary = project.planning_summary;
  return (
    <article className={cx("panel p-4 transition", selected && "ring-2 ring-slate-800/20")}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-display text-xl font-semibold">{project.name}</h3>
            <span className={cx("rounded-full px-2 py-1 text-xs font-semibold", statusTone(project.status))}>
              {project.status}
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-600">
            Start {formatDate(project.planned_start)} | Requirements {project.requirement_count}
          </p>
          {project.description && <p className="mt-2 text-sm text-slate-600">{project.description}</p>}
        </div>
        <div className={cx("rounded-2xl border px-3 py-2 text-xs font-medium", summaryTone(project.summary_mode))}>
          {project.summary_mode === "authoritative"
            ? "Live Pipeline"
            : project.summary_mode === "preview_required"
              ? "Preview Required"
              : "Archived"}
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {planningSummary ? (
          <>
            <SummaryMetric label="Required" value={planningSummary.required_total} />
            <SummaryMetric label="On-Time Gap" value={planningSummary.shortage_at_start_total} tone="amber" />
            <SummaryMetric label="Remaining" value={planningSummary.remaining_shortage_total} />
            <SummaryMetric
              label="Generic Before"
              value={planningSummary.cumulative_generic_consumed_before_total}
              tone="sky"
            />
          </>
        ) : (
          <>
            <SummaryMetric label="Required Rows" value={project.requirement_count} />
            <SummaryMetric label="Open RFQs" value={project.rfq_summary.open_batch_count} tone="amber" />
            <SummaryMetric label="Quoted Lines" value={project.rfq_summary.quoted_line_count} tone="emerald" />
            <SummaryMetric label="Ordered Lines" value={project.rfq_summary.ordered_line_count} tone="sky" />
          </>
        )}
      </div>

      <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
        <p>{project.summary_message}</p>
        <p className="mt-1 text-xs text-slate-500">
          RFQ: {project.rfq_summary.open_batch_count} open batches, {project.rfq_summary.quoted_line_count} quoted
          lines, {project.rfq_summary.ordered_line_count} ordered lines.
        </p>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button className="button-subtle" type="button" onClick={onOpenProject}>
          Open Project
        </button>
        <button className="button" type="button" onClick={onOpenBoard}>
          {project.status === "PLANNING" ? "Preview In Board" : "Open Board"}
        </button>
        <button className="button-subtle" type="button" onClick={onOpenRfq}>
          RFQ Context
        </button>
      </div>
    </article>
  );
}

function ProjectDrawerContent(_props: {
  projectId: number;
  onOpenItem: (itemId: number, label: string) => void;
  onPreviewBoard: (projectId: number) => void;
  onRefresh: () => Promise<void>;
  onDirtyChange: (isDirty: boolean) => void;
  rfqSummary: WorkspaceProjectSummary["rfq_summary"];
  active: boolean;
}) {
  const { projectId, onOpenItem, onPreviewBoard, onRefresh, onDirtyChange, rfqSummary, active } = _props;
  const { data, error, isLoading, mutate } = useSWR(active ? `/projects/${projectId}` : null, () =>
    apiGet<ProjectDetail>(`/projects/${projectId}`),
  );

  return (
    <div className="space-y-5">
      {isLoading && <p className="text-sm text-slate-500">Loading project context...</p>}
      {error && <p className="text-sm text-red-600">{String(error)}</p>}
      {data && (
        <>
          <section className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-display text-2xl font-semibold">{data.name}</h2>
              <span className={cx("rounded-full px-2 py-1 text-xs font-semibold", statusTone(data.status))}>
                {data.status}
              </span>
            </div>
            <p className="text-sm text-slate-600">
              Requirements {data.requirements.length} | RFQ batches {rfqSummary.total_batches}
            </p>
            {data.description && <p className="text-sm text-slate-600">{data.description}</p>}
            <div className="flex flex-wrap gap-2 text-sm">
              <button className="button" type="button" onClick={() => onPreviewBoard(projectId)}>
                {data.status === "PLANNING" ? "Preview In Board" : "Open Board"}
              </button>
              <Link className="button-subtle" to="/projects">
                Open Full Project Editor
              </Link>
              <Link className="button-subtle" to="/planning">
                Open Legacy Planning Page
              </Link>
            </div>
            <p className="text-xs text-slate-500">
              Use the inline editor below for moderate changes. For spreadsheet-heavy updates, widen the drawer or
              switch to the dedicated Projects page.
            </p>
          </section>

          <section className="grid gap-3 md:grid-cols-3">
            <SummaryMetric label="Open Batches" value={rfqSummary.open_batch_count} tone="amber" />
            <SummaryMetric label="Quoted Lines" value={rfqSummary.quoted_line_count} tone="emerald" />
            <SummaryMetric label="Ordered Lines" value={rfqSummary.ordered_line_count} tone="sky" />
          </section>

          <ProjectEditor
            projectId={projectId}
            title="Project Editor"
            submitLabel="Save Project"
            autoFocusField="planned_start"
            active={active}
            onDirtyChange={onDirtyChange}
            onOpenItem={onOpenItem}
            onSaved={async () => {
              await Promise.all([mutate(), onRefresh()]);
            }}
          />
        </>
      )}
    </div>
  );
}

function ItemDrawerContent(_props: {
  itemId: number;
  previewProjectId: number | null;
  targetDate: string | null;
  onOpenProject: (projectId: number, label: string) => void;
  onOpenRfq: (projectId: number, itemId: number | null, label?: string) => void;
  active: boolean;
}) {
  const { itemId, previewProjectId, targetDate, onOpenProject, onOpenRfq, active } = _props;
  const { data: itemData, error: itemError } = useSWR(active ? `/items/${itemId}` : null, () =>
    apiGet<Item>(`/items/${itemId}`),
  );
  const { data: inventoryResp } = useSWR(active ? `/workspace-item-inventory-${itemId}` : null, () =>
    apiGetWithPagination<InventoryRow[]>(`/inventory?item_id=${itemId}&per_page=200`),
  );
  const { data: flowData } = useSWR(active ? `/items/${itemId}/flow` : null, () =>
    apiGet<ItemFlowTimeline>(`/items/${itemId}/flow`),
  );
  const { data: reservationsResp } = useSWR(active ? `/workspace-item-reservations-${itemId}` : null, () =>
    apiGetWithPagination<ReservationRow[]>(`/reservations?item_id=${itemId}&status=ACTIVE&per_page=200`),
  );
  const ordersPath = `/orders?item_id=${itemId}&include_arrived=false&per_page=200`;
  const { data: ordersResp } = useSWR(active ? ordersPath : null, () => apiGetWithPagination<Order[]>(ordersPath));
  const planningPath = useMemo(() => {
    const params = new URLSearchParams();
    if (previewProjectId != null) params.set("preview_project_id", String(previewProjectId));
    if (targetDate) params.set("target_date", targetDate);
    const query = params.toString();
    return `/items/${itemId}/planning-context${query ? `?${query}` : ""}`;
  }, [itemId, previewProjectId, targetDate]);
  const { data: planningData } = useSWR(active ? planningPath : null, () => apiGet<ItemPlanningContext>(planningPath));

  const inventoryRows = inventoryResp?.data ?? [];
  const reservations = reservationsResp?.data ?? [];
  const orders = ordersResp?.data ?? [];

  return (
    <div className="space-y-5">
      {itemError && <p className="text-sm text-red-600">{String(itemError)}</p>}
      {itemData ? (
        <>
          <section className="space-y-2">
            <h2 className="font-display text-2xl font-semibold">{itemData.item_number}</h2>
            <p className="text-sm text-slate-600">
              {itemData.manufacturer_name} | Category {itemData.category ?? "-"}
            </p>
            {itemData.description && <p className="text-sm text-slate-600">{itemData.description}</p>}
            <div className="flex flex-wrap gap-2 text-sm">
              <Link className="button-subtle" to="/items">
                Open Items Page
              </Link>
              <Link className="button-subtle" to="/orders">
                Open Orders Page
              </Link>
            </div>
          </section>

          <section className="grid gap-3 md:grid-cols-4">
            <SummaryMetric label="Current Stock" value={flowData?.current_stock ?? 0} tone="emerald" />
            <SummaryMetric label="Locations" value={inventoryRows.length} />
            <SummaryMetric label="Open Orders" value={orders.length} tone="sky" />
            <SummaryMetric label="Active Reservations" value={reservations.length} tone="amber" />
          </section>

          <section className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="font-display text-lg font-semibold">Planning Allocation Context</h3>
                <p className="text-sm text-slate-600">
                  Cross-project demand and coverage for this item at target date {formatDate(planningData?.target_date ?? targetDate)}.
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
                  className={cx(
                    "rounded-2xl border px-4 py-4",
                    project.is_planning_preview ? "border-amber-300 bg-amber-50" : "border-slate-200",
                  )}
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="font-semibold">{project.project_name}</p>
                        <span className={cx("rounded-full px-2 py-1 text-xs font-semibold", statusTone(project.project_status))}>
                          {project.project_status}
                        </span>
                        {project.is_planning_preview && (
                          <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-800">
                            Preview
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-slate-600">Start {formatDate(project.planned_start)}</p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        className="button-subtle"
                        type="button"
                        onClick={() => onOpenProject(project.project_id, project.project_name)}
                      >
                        Project
                      </button>
                      <button
                        className="button-subtle"
                        type="button"
                        onClick={() => onOpenRfq(project.project_id, itemId, `${project.project_name} RFQ`)}
                      >
                        RFQ
                      </button>
                    </div>
                  </div>
                  <div className="mt-4 grid gap-3 lg:grid-cols-5">
                    <div className="rounded-xl border border-slate-200 bg-white px-3 py-3">
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Required</p>
                      <p className="mt-1 text-xl font-bold">{project.required_quantity}</p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-white px-3 py-3">
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Covered By Start</p>
                      <p className="mt-1 text-xl font-bold">{project.covered_on_time_quantity}</p>
                      <p className="text-xs text-slate-500">
                        Dedicated {project.dedicated_supply_by_start} | Generic {project.generic_allocated_quantity} / pool {project.generic_available_at_start}
                      </p>
                    </div>
                    <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-3">
                      <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">On-Time Gap</p>
                      <p className="mt-1 text-xl font-bold text-amber-900">{project.shortage_at_start}</p>
                    </div>
                    <div className="rounded-xl border border-sky-200 bg-sky-50 px-3 py-3">
                      <p className="text-xs font-semibold uppercase tracking-wide text-sky-700">Recovered Later</p>
                      <p className="mt-1 text-xl font-bold text-sky-900">{project.recovered_after_start_quantity}</p>
                      <p className="text-xs text-sky-700">
                        Generic {project.future_generic_recovery_quantity} | Dedicated {project.future_dedicated_recovery_quantity}
                      </p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Remaining</p>
                      <p className="mt-1 text-xl font-bold">{project.remaining_shortage_quantity}</p>
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
                </div>
              ))}
              {!planningData?.projects.length && (
                <p className="rounded-2xl border border-dashed border-slate-300 px-4 py-5 text-sm text-slate-500">
                  No committed or previewed project allocation context for this item.
                </p>
              )}
            </div>
          </section>

          <section className="space-y-3">
            <h3 className="font-display text-lg font-semibold">Incoming Orders</h3>
            <div className="space-y-2">
              {orders.map((order) => (
                <div key={order.order_id} className="rounded-2xl border border-slate-200 px-4 py-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="font-semibold">
                        Order #{order.order_id} | Qty {order.order_amount}
                      </p>
                      <p className="text-sm text-slate-600">
                        {order.supplier_name} | ETA {formatDate(order.expected_arrival)} | {order.status}
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
                  No open orders for this item.
                </p>
              )}
            </div>
          </section>

          <section className="space-y-3">
            <h3 className="font-display text-lg font-semibold">Active Project Demand</h3>
            <div className="space-y-2">
              {reservations.map((reservation) => (
                <div key={reservation.reservation_id} className="rounded-2xl border border-slate-200 px-4 py-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="font-semibold">
                        Reservation #{reservation.reservation_id} | Qty {reservation.quantity}
                      </p>
                      <p className="text-sm text-slate-600">
                        Deadline {formatDate(reservation.deadline)} | {reservation.purpose ?? "No purpose"}
                      </p>
                      <p className="text-xs text-slate-500">{reservation.project_name ?? "No linked project"}</p>
                    </div>
                    {reservation.project_id && (
                      <button
                        className="button-subtle"
                        type="button"
                        onClick={() =>
                          onOpenProject(
                            reservation.project_id ?? 0,
                            reservation.project_name ?? `Project #${reservation.project_id}`,
                          )
                        }
                      >
                        Open Project
                      </button>
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
            <h3 className="font-display text-lg font-semibold">Inventory By Location</h3>
            <div className="space-y-2">
              {inventoryRows.map((row) => (
                <div key={`${row.ledger_id}-${row.location}`} className="rounded-2xl border border-slate-200 px-4 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="font-semibold">{row.location}</p>
                      <p className="text-sm text-slate-500">Last updated {formatDate(row.last_updated)}</p>
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
                <div key={`${event.event_at}-${event.source_ref}`} className="rounded-2xl border border-slate-200 px-4 py-3">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="font-semibold">{event.reason}</p>
                      <p className="text-sm text-slate-600">
                        {event.event_at} | {event.source_ref}
                      </p>
                      {event.note && <p className="text-xs text-slate-500">{event.note}</p>}
                    </div>
                    <div
                      className={cx(
                        "rounded-full px-3 py-1 text-sm font-semibold",
                        event.delta >= 0 ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800",
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
        </>
      ) : (
        <p className="text-sm text-slate-500">Loading item context...</p>
      )}
    </div>
  );
}

function RfqDrawerContent(_props: {
  projectId: number;
  itemId: number | null;
  onOpenItem: (itemId: number, label: string) => void;
  onRefresh: () => Promise<void>;
  onDirtyChange: (isDirty: boolean) => void;
  active: boolean;
}) {
  const { projectId, itemId, onOpenItem, onRefresh, onDirtyChange, active } = _props;
  return (
    <div className="space-y-5">
      <section className="space-y-2">
        <h2 className="font-display text-2xl font-semibold">RFQ Context</h2>
        <p className="text-sm text-slate-600">
          Update batch fields, supplier follow-up, ETA, and linked-order details directly from the workspace.
        </p>
        <div className="flex flex-wrap gap-2 text-sm">
          <Link className="button-subtle" to="/rfq">
            Open Full RFQ Page
          </Link>
          <Link className="button-subtle" to="/orders">
            Open Orders Page
          </Link>
        </div>
        {itemId != null && (
          <p className="text-xs text-slate-500">
            Lines for the selected item are highlighted when present. Other lines stay available so the batch can still be completed in place.
          </p>
        )}
      </section>

      <RfqBatchEditor
        fixedProjectId={projectId}
        highlightedItemId={itemId}
        showFilters={false}
        active={active}
        onOpenItem={onOpenItem}
        onDirtyChange={onDirtyChange}
        onSaved={onRefresh}
      />
    </div>
  );
}

function PlanningBoardRow({
  row,
  projectId,
  onOpenItem,
  onOpenRfq,
}: {
  row: PlanningAnalysisRow;
  projectId: number;
  onOpenItem: (itemId: number, label: string) => void;
  onOpenRfq: (projectId: number, itemId: number | null, label?: string) => void;
}) {
  return (
    <tr className="border-b border-slate-100 align-top">
      <td className="px-2 py-3">
        <p className="font-semibold">{row.item_number ?? `#${row.item_id}`}</p>
        <p className="text-xs text-slate-500">{row.manufacturer_name ?? "-"}</p>
      </td>
      <td className="px-2 py-3">{row.required_quantity}</td>
      <td className="px-2 py-3">
        <p className="font-semibold">{row.covered_on_time_quantity}</p>
        <p className="text-xs text-slate-500">
          Dedicated {row.dedicated_supply_by_start} | Generic {row.generic_allocated_quantity} / pool {row.generic_available_at_start}
        </p>
      </td>
      <td className="px-2 py-3 font-semibold text-amber-700">{row.shortage_at_start}</td>
      <td className="px-2 py-3">
        <p className="font-semibold">{row.recovered_after_start_quantity}</p>
        <p className="text-xs text-slate-500">
          Generic {row.future_generic_recovery_quantity} | Dedicated {row.future_dedicated_recovery_quantity}
        </p>
      </td>
      <td className="px-2 py-3 font-semibold text-slate-900">{row.remaining_shortage_quantity}</td>
      <td className="px-2 py-3">
        <PlanningSourceList title="By Start" sources={row.supply_sources_by_start} emptyLabel="No on-time coverage sources." />
      </td>
      <td className="px-2 py-3">
        <PlanningSourceList
          title="Later Recovery"
          sources={row.recovery_sources_after_start}
          emptyLabel="No later recovery source yet."
        />
      </td>
      <td className="px-2 py-3">
        <div className="flex flex-col gap-2">
          <button
            className="button-subtle"
            type="button"
            onClick={() => onOpenItem(row.item_id, row.item_number ?? `Item #${row.item_id}`)}
          >
            Item
          </button>
          <button
            className="button-subtle"
            type="button"
            onClick={() => onOpenRfq(projectId, row.item_id, row.item_number ?? `RFQ item ${row.item_id}`)}
          >
            RFQ
          </button>
        </div>
      </td>
    </tr>
  );
}

export function WorkspacePage() {
  const [view, setView] = useState<WorkspaceView>("summary");
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [analysisDateDraft, setAnalysisDateDraft] = useState("");
  const [analysisDateApplied, setAnalysisDateApplied] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [working, setWorking] = useState(false);
  const [drawerStack, setDrawerStack] = useState<DrawerContext[]>([]);
  const [dirtyDrawerLabels, setDirtyDrawerLabels] = useState<Record<string, string>>({});

  const {
    data: workspaceSummary,
    error: workspaceError,
    isLoading: workspaceLoading,
    mutate: mutateWorkspace,
  } = useSWR("/workspace/summary", () => apiGet<WorkspaceSummary>("/workspace/summary"));

  const projects = workspaceSummary?.projects ?? [];
  const pipeline = workspaceSummary?.pipeline ?? [];

  useEffect(() => {
    const selectedStillExists =
      selectedProjectId != null && projects.some((project) => project.project_id === selectedProjectId);
    if (selectedStillExists) return;
    const defaultProject = pickDefaultProject(projects);
    if (!defaultProject) {
      setSelectedProjectId(null);
      setAnalysisDateDraft("");
      setAnalysisDateApplied("");
      setActionMessage("");
      return;
    }
    setSelectedProjectId(defaultProject.project_id);
    setAnalysisDateDraft(defaultProject.planned_start ?? "");
    setAnalysisDateApplied(defaultProject.planned_start ?? "");
  }, [projects, selectedProjectId]);

  const selectedProject = useMemo(
    () => projects.find((project) => project.project_id === selectedProjectId) ?? null,
    [projects, selectedProjectId],
  );

  useEffect(() => {
    if (!selectedProject) return;
    setAnalysisDateDraft(selectedProject.planned_start ?? "");
    setAnalysisDateApplied(selectedProject.planned_start ?? "");
    setActionMessage("");
  }, [selectedProject?.project_id]);

  const analysisKey = useMemo(() => {
    if (!selectedProject) return null;
    const params = new URLSearchParams();
    if (analysisDateApplied.trim()) params.set("target_date", analysisDateApplied.trim());
    const query = params.toString();
    return `/projects/${selectedProject.project_id}/planning-analysis${query ? `?${query}` : ""}`;
  }, [analysisDateApplied, selectedProject?.project_id]);

  const {
    data: analysisData,
    error: analysisError,
    isLoading: analysisLoading,
    mutate: mutateAnalysis,
  } = useSWR(analysisKey, () => apiGet<PlanningAnalysisResult>(analysisKey ?? ""));
  const selectedAnalysisTargetDate =
    analysisData && analysisData.project.project_id === selectedProject?.project_id
      ? analysisData.target_date
      : null;

  const boardPipeline = analysisData?.pipeline ?? pipeline;
  const activeDrawer = drawerStack[drawerStack.length - 1] ?? null;
  const previewDirty = analysisDateDraft.trim() !== analysisDateApplied.trim();
  const persistedDate = selectedProject?.planned_start ?? "";
  const canPersistDate = analysisDateDraft.trim() !== "" && analysisDateDraft.trim() !== persistedDate;

  const statusCounts = useMemo(
    () => ({
      active: projects.filter((project) => project.status === "ACTIVE").length,
      confirmed: projects.filter((project) => project.status === "CONFIRMED").length,
      planning: projects.filter((project) => project.status === "PLANNING").length,
    }),
    [projects],
  );

  useEffect(() => {
    if (!selectedProject) return;
    const nextBoardDate = nextSynchronizedBoardDate({
      analysisDateDraft,
      analysisDateApplied,
      projectPlannedStart: selectedProject.planned_start,
      analysisTargetDate: selectedAnalysisTargetDate,
    });
    if (nextBoardDate == null) return;
    setAnalysisDateDraft(nextBoardDate);
    setAnalysisDateApplied(nextBoardDate);
  }, [
    analysisDateApplied,
    analysisDateDraft,
    selectedAnalysisTargetDate,
    selectedProject?.planned_start,
    selectedProject?.project_id,
  ]);

  useEffect(() => {
    setDirtyDrawerLabels((current) =>
      Object.fromEntries(
        Object.entries(current).filter(([key]) => drawerStack.some((entry) => entry.key === key)),
      ),
    );
  }, [drawerStack]);

  const hasDirtyDrawers = drawerStack.some((entry) => Boolean(dirtyDrawerLabels[entry.key]));

  useBeforeUnload(
    (event) => {
      if (!hasDirtyDrawers) return;
      event.preventDefault();
      event.returnValue = "";
    },
    { capture: true },
  );
  usePrompt({
    when: hasDirtyDrawers,
    message: "Discard unsaved workspace drawer changes?",
  });

  async function refreshWorkspace() {
    await Promise.all([mutateWorkspace(), analysisKey ? mutateAnalysis() : Promise.resolve(undefined)]);
  }

  function setDrawerDirty(key: string, label: string, isDirty: boolean) {
    setDirtyDrawerLabels((current) => {
      if (isDirty && current[key] === label) return current;
      if (!isDirty && !current[key]) return current;
      const next = { ...current };
      if (isDirty) {
        next[key] = label;
      } else {
        delete next[key];
      }
      return next;
    });
  }

  function confirmDiscard(keys: string[]): boolean {
    const labels = Array.from(
      new Set(keys.map((key) => dirtyDrawerLabels[key]).filter((value): value is string => Boolean(value))),
    );
    if (!labels.length) return true;
    return window.confirm(`Discard unsaved changes in ${labels.join(", ")}?`);
  }

  function pushDrawer(context: DrawerContext) {
    const resolved = resolveDrawerStackPush(drawerStack, context);
    if (resolved.discardedKeys.length && !confirmDiscard(resolved.discardedKeys)) return;
    setDrawerStack(resolved.nextStack);
  }

  function openProjectDrawer(projectId: number, label?: string) {
    const project = projects.find((entry) => entry.project_id === projectId);
    pushDrawer({
      key: `project:${projectId}`,
      type: "project",
      projectId,
      label: label ?? project?.name ?? `Project #${projectId}`,
    });
  }

  function openItemDrawer(itemId: number, label?: string) {
    pushDrawer({
      key: `item:${itemId}`,
      type: "item",
      itemId,
      label: label ?? `Item #${itemId}`,
    });
  }

  function openRfqDrawer(projectId: number, itemId: number | null, label?: string) {
    pushDrawer({
      key: `rfq:${projectId}:${itemId ?? "all"}`,
      type: "rfq",
      projectId,
      itemId,
      label: label ?? "RFQ Context",
    });
  }

  function openBoard(projectId: number) {
    const project = projects.find((entry) => entry.project_id === projectId);
    setSelectedProjectId(projectId);
    setAnalysisDateDraft(project?.planned_start ?? "");
    setAnalysisDateApplied(project?.planned_start ?? "");
    setView("board");
  }

  function previewImpact() {
    setActionMessage("");
    setAnalysisDateApplied(analysisDateDraft.trim());
  }

  function requestCloseDrawer() {
    if (!confirmDiscard(drawerStack.map((entry) => entry.key))) return;
    setDrawerStack([]);
  }

  function requestNavigateDrawer(index: number) {
    const discardedKeys = drawerStack.slice(index + 1).map((entry) => entry.key);
    if (!confirmDiscard(discardedKeys)) return;
    setDrawerStack((current) => current.slice(0, index + 1));
  }

  async function savePlannedStartFromBoard() {
    if (!selectedProjectId) return;
    setWorking(true);
    setActionMessage("");
    try {
      await apiSend(`/projects/${selectedProjectId}`, {
        method: "PUT",
        body: JSON.stringify({
          planned_start: analysisDateDraft.trim() || null,
        }),
      });
      setAnalysisDateApplied(analysisDateDraft.trim());
      setActionMessage("Planned start saved.");
      await refreshWorkspace();
    } catch (saveError) {
      setActionMessage(`Save failed: ${String(saveError ?? "")}`);
    } finally {
      setWorking(false);
    }
  }

  async function createRfqBatch() {
    if (!selectedProjectId) return;
    const isDraft = selectedProject?.status === "PLANNING";
    const confirmed = window.confirm(
      isDraft
        ? "Create an RFQ batch from current on-time gaps? This will confirm the draft project."
        : "Create an RFQ batch from current on-time gaps?",
    );
    if (!confirmed) return;
    setWorking(true);
    setActionMessage("");
    try {
      const payload = await apiSend<{ rfq_id: number }>(`/projects/${selectedProjectId}/rfq-batches`, {
        method: "POST",
        body: JSON.stringify({
          target_date: selectedAnalysisTargetDate ?? (analysisDateApplied.trim() || null),
        }),
      });
      setActionMessage(`Created RFQ batch #${payload.rfq_id}.`);
      await refreshWorkspace();
      openRfqDrawer(selectedProjectId, null, "RFQ Context");
    } catch (rfqError) {
      setActionMessage(`RFQ creation failed: ${String(rfqError ?? "")}`);
    } finally {
      setWorking(false);
    }
  }

  async function downloadPlanningExport() {
    if (!selectedProjectId) return;
    const params = new URLSearchParams({ project_id: String(selectedProjectId) });
    if (selectedAnalysisTargetDate) params.set("target_date", selectedAnalysisTargetDate);
    try {
      await apiDownload(
        `/workspace/planning-export?${params.toString()}`,
        `workspace_planning_project_${selectedProjectId}.csv`,
      );
      setActionMessage("Planning export downloaded.");
    } catch (error) {
      setActionMessage(`Export failed: ${String(error ?? "")}`);
    }
  }

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-bold">Workspace</h1>
          <p className="mt-1 text-sm text-slate-600">
            Summary-first planning surface for Projects, sequential netting, and RFQ follow-up.
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Existing pages remain available for heavy editing:{" "}
            <Link className="font-semibold text-slate-700 underline" to="/projects">
              Projects
            </Link>
            ,{" "}
            <Link className="font-semibold text-slate-700 underline" to="/planning">
              Planning
            </Link>
            , and{" "}
            <Link className="font-semibold text-slate-700 underline" to="/rfq">
              RFQ
            </Link>
            .
          </p>
        </div>
        <div className="grid min-w-[280px] gap-3 sm:grid-cols-3">
          <SummaryMetric label="Active" value={statusCounts.active} tone="emerald" />
          <SummaryMetric label="Confirmed" value={statusCounts.confirmed} tone="sky" />
          <SummaryMetric label="Planning" value={statusCounts.planning} tone="amber" />
        </div>
      </section>

      <section className="flex flex-wrap gap-2">
        <button
          className={cx("button-subtle", view === "summary" && "border-slate-800 bg-slate-800 text-white")}
          type="button"
          onClick={() => setView("summary")}
        >
          Project Summary
        </button>
        <button
          className={cx("button-subtle", view === "pipeline" && "border-slate-800 bg-slate-800 text-white")}
          type="button"
          onClick={() => setView("pipeline")}
        >
          Pipeline
        </button>
        <button
          className={cx("button-subtle", view === "board" && "border-slate-800 bg-slate-800 text-white")}
          type="button"
          onClick={() => setView("board")}
          disabled={!selectedProjectId}
        >
          Planning Board
        </button>
      </section>

      {workspaceError && <p className="text-sm text-red-600">{String(workspaceError)}</p>}
      {workspaceLoading && <p className="text-sm text-slate-500">Loading workspace summary...</p>}

      {view === "summary" && (
        <section className="grid gap-4 xl:grid-cols-2">
          {projects.map((project) => (
            <ProjectSummaryCard
              key={project.project_id}
              project={project}
              selected={project.project_id === selectedProjectId}
              onOpenProject={() => openProjectDrawer(project.project_id)}
              onOpenBoard={() => openBoard(project.project_id)}
              onOpenRfq={() => openRfqDrawer(project.project_id, null, `${project.name} RFQ`)}
            />
          ))}
          {!projects.length && !workspaceLoading && (
            <div className="panel p-6 text-sm text-slate-500">No projects available yet.</div>
          )}
        </section>
      )}

      {view === "pipeline" && (
        <section className="panel p-4">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-display text-xl font-semibold">Committed Pipeline</h2>
              <p className="text-sm text-slate-600">
                Committed projects are netted in planned-start order. Earlier backlog consumes later generic arrivals
                before newer projects can use them.
              </p>
            </div>
            <Link className="button-subtle" to="/planning">
              Open Legacy Planning Page
            </Link>
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
                      <p className="text-xs text-slate-500">#{row.project_id}</p>
                    </td>
                    <td className="px-2 py-3">
                      <span className={cx("rounded-full px-2 py-1 text-xs font-semibold", statusTone(row.status))}>
                        {row.status}
                      </span>
                    </td>
                    <td className="px-2 py-3">{row.planned_start}</td>
                    <td className="px-2 py-3">{row.required_total}</td>
                    <td className="px-2 py-3">{row.covered_on_time_total}</td>
                    <td className="px-2 py-3 font-semibold text-amber-700">{row.shortage_at_start_total}</td>
                    <td className="px-2 py-3">{row.remaining_shortage_total}</td>
                    <td className="px-2 py-3">{row.generic_committed_total}</td>
                    <td className="px-2 py-3">{row.cumulative_generic_consumed_before_total}</td>
                    <td className="px-2 py-3">
                      <div className="flex flex-wrap gap-2">
                        <button className="button-subtle" type="button" onClick={() => openProjectDrawer(row.project_id)}>
                          Project
                        </button>
                        <button className="button" type="button" onClick={() => openBoard(row.project_id)}>
                          Board
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {!pipeline.length && (
                  <tr>
                    <td className="px-2 py-5 text-slate-500" colSpan={10}>
                      No committed projects in the planning pipeline.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {view === "board" && (
        <div className="space-y-4">
          <section className="panel p-4">
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr),auto]">
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="font-display text-2xl font-semibold">
                    {analysisData?.project.name ?? selectedProject?.name ?? "Select a project"}
                  </h2>
                  {selectedProject && (
                    <span className={cx("rounded-full px-2 py-1 text-xs font-semibold", statusTone(selectedProject.status))}>
                      {selectedProject.status}
                    </span>
                  )}
                  {analysisData?.summary.is_planning_preview && (
                    <span className="rounded-full bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-800">
                      What-If Preview
                    </span>
                  )}
                </div>
                <p className="text-sm text-slate-600">
                  Server-driven preview of shortage exposure at the selected start date. Dedicated supply is consumed
                  before generic stock and generic arrivals.
                </p>
                <div className="grid gap-3 md:grid-cols-[200px,auto,auto,auto]">
                  <select
                    className="input"
                    value={selectedProjectId ?? ""}
                    onChange={(event) => openBoard(Number(event.target.value))}
                  >
                    {projects.map((project) => (
                      <option key={project.project_id} value={project.project_id}>
                        #{project.project_id} {project.name} ({project.status})
                      </option>
                    ))}
                  </select>
                  <input
                    className="input"
                    type="date"
                    value={analysisDateDraft}
                    onChange={(event) => setAnalysisDateDraft(event.target.value)}
                  />
                  <button className="button-subtle" type="button" disabled={!selectedProjectId} onClick={previewImpact}>
                    Preview Impact
                  </button>
                  <button className="button" type="button" disabled={!canPersistDate || working} onClick={savePlannedStartFromBoard}>
                    Save Planned Start
                  </button>
                </div>
                {previewDirty && (
                  <p className="text-xs text-amber-700">
                    Date input changed. Use <span className="font-semibold">Preview Impact</span> to refresh server
                    analysis before committing.
                  </p>
                )}
                {!!actionMessage && <p className="text-sm text-slate-700">{actionMessage}</p>}
                {analysisError && <p className="text-sm text-red-600">{String(analysisError)}</p>}
              </div>

              {analysisData?.summary && (
                <div className="grid min-w-[340px] gap-3 sm:grid-cols-2">
                  <SummaryMetric label="Required" value={analysisData.summary.required_total} />
                  <SummaryMetric label="Covered On Time" value={analysisData.summary.covered_on_time_total} tone="emerald" />
                  <SummaryMetric label="On-Time Gap" value={analysisData.summary.shortage_at_start_total} tone="amber" />
                  <SummaryMetric label="Remaining" value={analysisData.summary.remaining_shortage_total} />
                  <SummaryMetric label="Generic Committed" value={analysisData.summary.generic_committed_total} tone="sky" />
                  <SummaryMetric
                    label="Generic Before"
                    value={analysisData.summary.cumulative_generic_consumed_before_total}
                    tone="sky"
                  />
                </div>
              )}
            </div>
          </section>

          <section className="panel p-4">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="font-display text-lg font-semibold">Project Timeline</h3>
                <p className="text-sm text-slate-600">
                  Timeline cards stay server-aligned with the current board preview. Draft project previews appear here
                  only when selected.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {selectedProjectId && (
                  <button className="button-subtle" type="button" onClick={() => openProjectDrawer(selectedProjectId)}>
                    Open Project Drawer
                  </button>
                )}
                {selectedProjectId && (
                  <button className="button-subtle" type="button" disabled={working || !analysisData} onClick={() => void downloadPlanningExport()}>
                    Export CSV
                  </button>
                )}
                {selectedProjectId && (
                  <button
                    className="button"
                    type="button"
                    disabled={working || !analysisData || analysisData.summary.shortage_at_start_total <= 0}
                    onClick={createRfqBatch}
                  >
                    Create RFQ From Gaps
                  </button>
                )}
              </div>
            </div>
            <div className="flex gap-3 overflow-x-auto pb-2">
              {boardPipeline.map((row) => (
                <button
                  key={`${row.project_id}-${row.is_planning_preview ? "preview" : "committed"}`}
                  type="button"
                  className={cx(
                    "min-w-[250px] rounded-2xl border px-4 py-4 text-left transition",
                    row.project_id === selectedProjectId
                      ? "border-slate-900 bg-slate-900 text-white"
                      : "border-slate-200 bg-white hover:border-slate-300",
                  )}
                  onClick={() => openBoard(row.project_id)}
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-semibold">{row.name}</p>
                    <span
                      className={cx(
                        "rounded-full px-2 py-1 text-[11px] font-semibold",
                        row.project_id === selectedProjectId ? "bg-white/10 text-white" : statusTone(row.status),
                      )}
                    >
                      {row.status}
                    </span>
                  </div>
                  <p className={cx("mt-2 text-xs", row.project_id === selectedProjectId ? "text-slate-200" : "text-slate-500")}>
                    {row.planned_start}
                    {row.is_planning_preview ? " | preview" : ""}
                  </p>
                  <div
                    className={cx(
                      "mt-3 grid grid-cols-2 gap-2 text-xs",
                      row.project_id === selectedProjectId ? "text-slate-100" : "text-slate-600",
                    )}
                  >
                    <div className="rounded-xl bg-black/5 px-2 py-2">
                      <p className="font-semibold">On-Time Gap</p>
                      <p>{row.shortage_at_start_total}</p>
                    </div>
                    <div className="rounded-xl bg-black/5 px-2 py-2">
                      <p className="font-semibold">Generic Before</p>
                      <p>{row.cumulative_generic_consumed_before_total}</p>
                    </div>
                  </div>
                </button>
              ))}
              {!boardPipeline.length && (
                <div className="rounded-2xl border border-dashed border-slate-300 px-5 py-6 text-sm text-slate-500">
                  No planning timeline available yet.
                </div>
              )}
            </div>
          </section>

          <section className="panel p-4">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="font-display text-lg font-semibold">Netting Workspace Grid</h3>
                <p className="text-sm text-slate-600">
                  Supply-source chips show what covers the row by the project start date and what only recovers backlog
                  later.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Link className="button-subtle" to="/planning">
                  Legacy Planning
                </Link>
                <Link className="button-subtle" to="/rfq">
                  Legacy RFQ
                </Link>
              </div>
            </div>
            {analysisLoading && <p className="text-sm text-slate-500">Loading planning board...</p>}
            {!analysisLoading && analysisData && (
              <div className="overflow-x-auto">
                <table className="min-w-[1520px] text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-slate-500">
                      <th className="px-2 py-2">Item</th>
                      <th className="px-2 py-2">Required</th>
                      <th className="px-2 py-2">Covered By Start</th>
                      <th className="px-2 py-2">On-Time Gap</th>
                      <th className="px-2 py-2">Recovered Later</th>
                      <th className="px-2 py-2">Remaining</th>
                      <th className="px-2 py-2">Coverage Breakdown</th>
                      <th className="px-2 py-2">Recovery Breakdown</th>
                      <th className="px-2 py-2">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analysisData.rows.map((row) => (
                      <PlanningBoardRow
                        key={row.item_id}
                        row={row}
                        projectId={analysisData.project.project_id}
                        onOpenItem={openItemDrawer}
                        onOpenRfq={openRfqDrawer}
                      />
                    ))}
                    {!analysisData.rows.length && (
                      <tr>
                        <td className="px-2 py-5 text-slate-500" colSpan={9}>
                          No requirement rows for the selected project.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      )}

      {activeDrawer && (
        <WorkspaceDrawer
          breadcrumbs={drawerStack.map((entry) => ({ key: entry.key, label: entry.label }))}
          onClose={requestCloseDrawer}
          onBack={drawerStack.length > 1 ? () => requestNavigateDrawer(drawerStack.length - 2) : undefined}
          onNavigate={requestNavigateDrawer}
        >
          {drawerStack.map((entry, index) => {
            const active = index === drawerStack.length - 1;
            return (
              <div
                key={entry.key}
                data-drawer-panel-active={active ? "true" : undefined}
                hidden={!active}
                aria-hidden={!active}
              >
                {entry.type === "project" && (
                  <ProjectDrawerContent
                    projectId={entry.projectId}
                    rfqSummary={
                      projects.find((project) => project.project_id === entry.projectId)?.rfq_summary ??
                      EMPTY_RFQ_SUMMARY
                    }
                    active={active}
                    onOpenItem={openItemDrawer}
                    onPreviewBoard={openBoard}
                    onRefresh={refreshWorkspace}
                    onDirtyChange={(isDirty) => setDrawerDirty(entry.key, entry.label, isDirty)}
                  />
                )}
                {entry.type === "item" && (
                  <ItemDrawerContent
                    itemId={entry.itemId}
                    previewProjectId={selectedProject?.project_id ?? null}
                    targetDate={selectedAnalysisTargetDate ?? (analysisDateApplied.trim() || null)}
                    active={active}
                    onOpenProject={openProjectDrawer}
                    onOpenRfq={openRfqDrawer}
                  />
                )}
                {entry.type === "rfq" && (
                  <RfqDrawerContent
                    projectId={entry.projectId}
                    itemId={entry.itemId}
                    active={active}
                    onOpenItem={openItemDrawer}
                    onRefresh={refreshWorkspace}
                    onDirtyChange={(isDirty) => setDrawerDirty(entry.key, entry.label, isDirty)}
                  />
                )}
              </div>
            );
          })}
        </WorkspaceDrawer>
      )}
    </div>
  );
}
