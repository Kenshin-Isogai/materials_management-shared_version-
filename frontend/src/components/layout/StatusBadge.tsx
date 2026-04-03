import { cn } from "@/lib/utils";

type StatusBadgeProps = {
  status: string;
  className?: string;
};

const toneMap: Record<string, string> = {
  ACTIVE: "bg-emerald-100 text-emerald-800",
  CONFIRMED: "bg-sky-100 text-sky-800",
  PLANNING: "bg-amber-100 text-amber-800",
  COMPLETED: "bg-slate-100 text-slate-600",
  CANCELLED: "bg-rose-100 text-rose-700",
  OPEN: "bg-emerald-100 text-emerald-800",
  CLOSED: "bg-slate-100 text-slate-600",
  DRAFT: "bg-amber-100 text-amber-800",
  SENT: "bg-sky-100 text-sky-800",
  QUOTED: "bg-indigo-100 text-indigo-800",
  ORDERED: "bg-emerald-100 text-emerald-800",
  RELEASED: "bg-slate-100 text-slate-600",
  CONSUMED: "bg-slate-100 text-slate-600",
};

export function StatusBadge({ status, className }: StatusBadgeProps) {
  const tone = toneMap[status] ?? "bg-slate-100 text-slate-600";
  return (
    <span
      className={cn(
        "inline-block rounded-md px-2 py-0.5 text-xs font-semibold",
        tone,
        className,
      )}
    >
      {status}
    </span>
  );
}
