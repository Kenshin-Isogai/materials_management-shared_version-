import { ApiErrorNotice } from "@/components/ApiErrorNotice";
import type {
  ItemImportJobDetail,
  ItemImportJobEffect,
  ItemImportJobSummary,
} from "@/features/items/types";

export interface ItemImportHistoryProps {
  importJobs: ItemImportJobSummary[];
  importJobsLoading: boolean;
  importJobsError: unknown;
  importJobsMessage: string;
  importJobBusyId: number | null;
  selectedImportJobId: number | null;
  selectedImportJobData: ItemImportJobDetail | undefined;
  importJobDetailLoading: boolean;
  importJobDetailError: unknown;
  onRefresh: () => void;
  onSelectJob: (jobId: number) => void;
  onUndoJob: (job: ItemImportJobSummary) => void;
  onRedoJob: (job: ItemImportJobSummary) => void;
}

export function ItemImportHistory({
  importJobs,
  importJobsLoading,
  importJobsError,
  importJobsMessage,
  importJobBusyId,
  selectedImportJobId,
  selectedImportJobData,
  importJobDetailLoading,
  importJobDetailError,
  onRefresh,
  onSelectJob,
  onUndoJob,
  onRedoJob,
}: ItemImportHistoryProps) {
  const selectedImportJob = selectedImportJobData?.job;
  const selectedImportJobIssues = (selectedImportJobData?.effects ?? []).filter(
    (row: ItemImportJobEffect) => row.status !== "created"
  );

  return (
    <section className="panel p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-display text-lg font-semibold">Items Import History</h2>
        <button className="button-subtle" type="button" onClick={onRefresh}>
          Refresh
        </button>
      </div>
      <p className="text-sm text-slate-600">
        Undo/redo is available per items import job. Undo is blocked if imported rows were changed
        later.
      </p>
      {importJobsMessage && <p className="mt-2 text-sm text-signal">{importJobsMessage}</p>}
      {importJobsLoading && <p className="mt-2 text-sm text-slate-500">Loading import jobs...</p>}
      {importJobsError ? <ApiErrorNotice error={importJobsError} area="item import job data" className="mt-2" /> : null}
      {importJobs.length > 0 ? (
        <div className="mt-3 overflow-x-auto">
          <table className="min-w-[980px] text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-500">
                <th className="px-2 py-2">Job</th>
                <th className="px-2 py-2">Created</th>
                <th className="px-2 py-2">Source</th>
                <th className="px-2 py-2">Lifecycle</th>
                <th className="px-2 py-2">Result</th>
                <th className="px-2 py-2">Action</th>
              </tr>
            </thead>
            <tbody>
              {importJobs.map((job) => (
                <tr key={job.import_job_id} className="border-b border-slate-100">
                  <td className="px-2 py-2 font-semibold">#{job.import_job_id}</td>
                  <td className="px-2 py-2">{job.created_at}</td>
                  <td className="px-2 py-2">{job.source_name}</td>
                  <td className="px-2 py-2">
                    {job.lifecycle_state}
                    {job.undone_at ? ` (at ${job.undone_at})` : ""}
                  </td>
                  <td className="px-2 py-2">
                    {job.status} | processed={job.processed}, created={job.created_count},
                    duplicates={job.duplicate_count}, failed={job.failed_count}
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex flex-wrap gap-2">
                      <button
                        className="button-subtle"
                        type="button"
                        onClick={() => onSelectJob(job.import_job_id)}
                        disabled={importJobBusyId !== null}
                      >
                        View
                      </button>
                      {job.lifecycle_state === "active" ? (
                        <button
                          className="button-subtle"
                          type="button"
                          onClick={() => onUndoJob(job)}
                          disabled={importJobBusyId !== null}
                        >
                          Undo
                        </button>
                      ) : (
                        <button
                          className="button-subtle"
                          type="button"
                          onClick={() => onRedoJob(job)}
                          disabled={importJobBusyId !== null}
                        >
                          Redo
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="mt-2 text-sm text-slate-500">No items import jobs yet.</p>
      )}
      {selectedImportJobId != null && (
        <div className="mt-4 rounded-xl border border-slate-200 bg-slate-50 p-3">
          <p className="text-sm font-semibold text-slate-900">Selected Job #{selectedImportJobId}</p>
          {importJobDetailLoading && <p className="mt-2 text-sm text-slate-500">Loading job detail...</p>}
          {importJobDetailError ? <ApiErrorNotice error={importJobDetailError} area="item import job detail" className="mt-2" /> : null}
          {selectedImportJob && (
            <>
              <p className="mt-2 text-sm text-slate-700">
                status={selectedImportJob.status}, lifecycle={selectedImportJob.lifecycle_state},
                processed={selectedImportJob.processed}, created={selectedImportJob.created_count},
                duplicates={selectedImportJob.duplicate_count}, failed={selectedImportJob.failed_count}
              </p>
              {selectedImportJobIssues.length > 0 ? (
                <div className="mt-2 overflow-x-auto rounded-lg border border-amber-200 bg-amber-50 p-2">
                  <p className="mb-2 text-sm font-semibold text-amber-900">Rows with issues</p>
                  <table className="min-w-[860px] text-sm">
                    <thead>
                      <tr className="border-b border-amber-200 text-left text-amber-800">
                        <th className="px-2 py-1">Row</th>
                        <th className="px-2 py-1">Status</th>
                        <th className="px-2 py-1">Entry</th>
                        <th className="px-2 py-1">Item</th>
                        <th className="px-2 py-1">Supplier</th>
                        <th className="px-2 py-1">Canonical</th>
                        <th className="px-2 py-1">Units</th>
                        <th className="px-2 py-1">Code</th>
                        <th className="px-2 py-1">Message</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedImportJobIssues.map((row) => (
                        <tr key={row.effect_id} className="border-b border-amber-100">
                          <td className="px-2 py-1">{row.row_number}</td>
                          <td className="px-2 py-1">{row.status}</td>
                          <td className="px-2 py-1">{row.entry_type ?? "-"}</td>
                          <td className="px-2 py-1 font-semibold">{row.item_number ?? "-"}</td>
                          <td className="px-2 py-1">{row.supplier_name ?? "-"}</td>
                          <td className="px-2 py-1">{row.canonical_item_number ?? "-"}</td>
                          <td className="px-2 py-1">{row.units_per_order ?? "-"}</td>
                          <td className="px-2 py-1">{row.code ?? "-"}</td>
                          <td className="px-2 py-1">{row.message ?? "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="mt-2 text-sm text-slate-600">No duplicate/error rows in this job.</p>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}
