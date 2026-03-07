import { type KeyboardEvent as ReactKeyboardEvent, type ReactNode, useEffect, useRef, useState } from "react";

type DrawerBreadcrumb = {
  key: string;
  label: string;
};

type WorkspaceDrawerProps = {
  breadcrumbs: DrawerBreadcrumb[];
  onClose: () => void;
  onNavigate: (index: number) => void;
  onBack?: () => void;
  children: ReactNode;
};

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function WorkspaceDrawer({
  breadcrumbs,
  onClose,
  onNavigate,
  onBack,
  children,
}: WorkspaceDrawerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [expanded, setExpanded] = useState(false);
  const activeKey = breadcrumbs[breadcrumbs.length - 1]?.key ?? "";

  function resolveFocusableElements(): HTMLElement[] {
    const focusContainer = containerRef.current;
    if (!focusContainer) return [];
    const activePanel =
      focusContainer.querySelector<HTMLElement>("[data-drawer-panel-active='true']") ?? focusContainer;
    return Array.from(activePanel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
      (element) =>
        !element.hasAttribute("disabled") &&
        !element.closest("[hidden]") &&
        element.getClientRects().length > 0,
    );
  }

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  useEffect(() => {
    const focusContainer = containerRef.current;
    if (!focusContainer) return;
    const activePanel =
      focusContainer.querySelector<HTMLElement>("[data-drawer-panel-active='true']") ?? focusContainer;
    const focusable = resolveFocusableElements();
    const first =
      activePanel.querySelector<HTMLElement>("[data-autofocus='true']") ?? focusable[0];
    first?.focus();
  }, [activeKey, breadcrumbs.length]);

  function handleContainerKeyDown(event: ReactKeyboardEvent<HTMLElement>) {
    if (event.defaultPrevented) return;
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = resolveFocusableElements();
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement as HTMLElement | null;
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
      return;
    }
    if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-slate-950/35 p-2 backdrop-blur-sm"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <aside
        ref={containerRef}
        role="dialog"
        aria-modal="true"
        className={`flex h-full w-full flex-col overflow-hidden rounded-3xl border border-black/10 bg-white shadow-2xl transition-all ${
          expanded ? "max-w-[96vw]" : "max-w-[780px]"
        }`}
        onMouseDown={(event) => event.stopPropagation()}
        onKeyDown={handleContainerKeyDown}
      >
        <header className="flex items-center justify-between gap-3 border-b border-slate-200 px-5 py-4">
          <div className="min-w-0">
            <nav className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
              {breadcrumbs.map((crumb, index) => {
                const active = index === breadcrumbs.length - 1;
                return (
                  <button
                    key={crumb.key}
                    type="button"
                    className={`rounded-full px-2 py-1 transition ${
                      active
                        ? "bg-slate-900 text-white"
                        : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                    }`}
                    onClick={() => onNavigate(index)}
                  >
                    {crumb.label}
                  </button>
                );
              })}
            </nav>
          </div>
          <div className="flex items-center gap-2">
            {onBack && breadcrumbs.length > 1 && (
              <button className="button-subtle" type="button" onClick={onBack}>
                Back
              </button>
            )}
            <button
              className="button-subtle"
              type="button"
              onClick={() => setExpanded((current) => !current)}
            >
              {expanded ? "Normal Width" : "Expand"}
            </button>
            <button className="button-subtle" type="button" onClick={onClose}>
              Close
            </button>
          </div>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5">{children}</div>
      </aside>
    </div>
  );
}
