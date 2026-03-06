import { RfqBatchEditor } from "../components/RfqBatchEditor";

export function RfqPage() {
  return (
    <div className="space-y-6">
      <section>
        <h1 className="font-display text-3xl font-bold">RFQ Workspace</h1>
        <p className="mt-1 text-sm text-slate-600">
          Convert planning gaps into supplier conversations, finalize quantities and lead times,
          then link real orders back to the project.
        </p>
        <p className="mt-1 text-xs text-slate-500">
          A line marked <span className="font-semibold">QUOTED</span> counts as dedicated planned
          supply. Once an actual order exists, link it and the order becomes the dedicated source
          used by planning.
        </p>
      </section>

      <RfqBatchEditor />
    </div>
  );
}
