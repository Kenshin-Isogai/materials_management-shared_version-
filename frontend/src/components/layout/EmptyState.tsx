import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type EmptyStateProps = {
  message: string;
  action?: ReactNode;
  className?: string;
};

export function EmptyState({ message, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-slate-300 px-8 py-12 text-center",
        className,
      )}
    >
      <p className="text-sm text-muted-foreground">{message}</p>
      {action}
    </div>
  );
}
