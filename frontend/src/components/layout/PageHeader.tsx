import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

type PageHeaderProps = {
  title: string;
  description?: string;
  children?: ReactNode;
  className?: string;
};

export function PageHeader({
  title,
  description,
  children,
  className,
}: PageHeaderProps) {
  return (
    <section className={cn("flex items-start justify-between gap-4", className)}>
      <div>
        <h1 className="font-display text-3xl font-bold">{title}</h1>
        {description && (
          <p className="mt-1 text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      {children && <div className="flex items-center gap-2">{children}</div>}
    </section>
  );
}
