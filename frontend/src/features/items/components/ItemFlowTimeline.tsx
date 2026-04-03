import React, { type RefObject } from "react";
import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import type { ItemFlowTimeline as ItemFlowTimelineData } from "@/features/items/types";

export interface ItemFlowTimelineProps {
  selectedFlowItemId: number;
  selectedFlowData: ItemFlowTimelineData | undefined;
  selectedFlowLoading: boolean;
  selectedFlowError: unknown;
  flowPanelRef: RefObject<HTMLElement | null>;
  onClose: () => void;
}

export function ItemFlowTimeline({
  selectedFlowData,
  selectedFlowLoading,
  selectedFlowError,
  flowPanelRef,
  onClose,
}: ItemFlowTimelineProps) {
  return (
    <section className="panel p-4" ref={flowPanelRef as React.RefObject<HTMLElement>}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-lg font-semibold">Item Increase/Decrease Timeline</h2>
        <button className="button-subtle" type="button" onClick={onClose}>
          Close
        </button>
      </div>
      {selectedFlowLoading && <p className="text-sm text-slate-500">Loading timeline...</p>}
      {selectedFlowError ? <ApiErrorNotice error={selectedFlowError} area="item flow timeline" /> : null}
      {selectedFlowData && (
        <>
          <p className="mb-2 text-sm text-slate-700">
            <strong>{selectedFlowData.item_number}</strong> ({selectedFlowData.manufacturer_name}) / Current STOCK: <strong>{selectedFlowData.current_stock}</strong>
          </p>
          <p className="mb-3 text-xs text-slate-500">
            This timeline combines transaction history (actual past changes) with open-order arrivals and active reservation deadlines (planned demand changes).
          </p>
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="px-2 py-2">When</th>
                  <th className="px-2 py-2">Change</th>
                  <th className="px-2 py-2">Direction</th>
                  <th className="px-2 py-2">Why</th>
                  <th className="px-2 py-2">Reference</th>
                  <th className="px-2 py-2">Note</th>
                </tr>
              </thead>
              <tbody>
                {selectedFlowData.events.map((event, idx) => (
                  <tr key={`${event.source_ref}-${event.event_at}-${idx}`} className="border-b border-slate-100">
                    <td className="px-2 py-2">{event.event_at}</td>
                    <td className={`px-2 py-2 font-semibold ${event.delta >= 0 ? "text-emerald-700" : "text-rose-700"}`}>
                      {event.delta >= 0 ? `+${event.delta}` : String(event.delta)}
                    </td>
                    <td className="px-2 py-2">{event.direction}</td>
                    <td className="px-2 py-2">{event.reason}</td>
                    <td className="px-2 py-2">{event.source_ref}</td>
                    <td className="px-2 py-2">{event.note ?? "-"}</td>
                  </tr>
                ))}
                {selectedFlowData.events.length === 0 && (
                  <tr>
                    <td className="px-2 py-3 text-slate-500" colSpan={6}>No increase/decrease events found for this item.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
