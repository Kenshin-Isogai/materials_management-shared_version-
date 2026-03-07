import {
  type KeyboardEvent as ReactKeyboardEvent,
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import useSWR from "swr";
import { apiGet } from "../lib/api";
import type {
  CatalogEntityType,
  CatalogSearchResponse,
  CatalogSearchResult,
} from "../lib/types";

const RECENT_LIMIT = 8;

const TYPE_LABELS: Record<CatalogEntityType, string> = {
  item: "Items",
  assembly: "Assemblies",
  supplier: "Suppliers",
  project: "Projects",
};

type SharedProps = {
  allowedTypes: CatalogEntityType[];
  placeholder?: string;
  recentKey: string;
  presentation?: "inline" | "popover";
  disabled?: boolean;
  seedQuery?: string;
  onQueryChange?: (value: string) => void;
};

type SingleProps = SharedProps & {
  mode?: "single";
  value: CatalogSearchResult | null;
  onChange: (value: CatalogSearchResult | null) => void;
};

type MultiProps = SharedProps & {
  mode: "multi";
  value: CatalogSearchResult[];
  onChange: (value: CatalogSearchResult[]) => void;
};

type CatalogPickerProps = SingleProps | MultiProps;

type ResultGroup = {
  type: CatalogEntityType;
  label: string;
  items: CatalogSearchResult[];
};

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

function recentStorageKey(key: string): string {
  return `mm.catalog-picker.recent.${key}`;
}

function resultKey(result: CatalogSearchResult): string {
  return `${result.entity_type}:${result.entity_id}`;
}

function loadRecentSelections(key: string): CatalogSearchResult[] {
  if (!isBrowser()) return [];
  try {
    const raw = window.localStorage.getItem(recentStorageKey(key));
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter(
        (entry): entry is CatalogSearchResult =>
          !!entry &&
          typeof entry === "object" &&
          typeof entry.entity_type === "string" &&
          typeof entry.entity_id === "number" &&
          typeof entry.display_label === "string"
      )
      .map((entry) => ({
        ...entry,
        value_text:
          typeof entry.value_text === "string" && entry.value_text.trim()
            ? entry.value_text
            : entry.display_label,
      }));
  } catch {
    return [];
  }
}

function saveRecentSelections(key: string, selections: CatalogSearchResult[]) {
  if (!isBrowser()) return;
  window.localStorage.setItem(recentStorageKey(key), JSON.stringify(selections.slice(0, RECENT_LIMIT)));
}

function groupResults(
  results: CatalogSearchResult[],
  allowedTypes: CatalogEntityType[]
): ResultGroup[] {
  return allowedTypes
    .map((type) => ({
      type,
      label: TYPE_LABELS[type],
      items: results.filter((result) => result.entity_type === type),
    }))
    .filter((group) => group.items.length > 0);
}

export function CatalogPicker(props: CatalogPickerProps) {
  const {
    allowedTypes,
    placeholder,
    recentKey,
    presentation = "popover",
    disabled,
    seedQuery,
    onQueryChange,
  } = props;
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const [recentSelections, setRecentSelections] = useState<CatalogSearchResult[]>(() =>
    loadRecentSelections(recentKey)
  );
  const deferredQuery = useDeferredValue(query.trim());
  const singleDisplayValue = props.mode === "multi" ? "" : props.value?.display_label ?? seedQuery ?? "";
  const lastSyncedSingleDisplayRef = useRef(singleDisplayValue);

  const selectedItems = props.mode === "multi" ? props.value : props.value ? [props.value] : [];
  const selectedSingle = props.mode === "multi" ? null : props.value;

  useEffect(() => {
    setRecentSelections(loadRecentSelections(recentKey));
  }, [recentKey]);

  useEffect(() => {
    if (props.mode !== "multi") {
      const selectionChanged = singleDisplayValue !== lastSyncedSingleDisplayRef.current;
      if (!isOpen || selectionChanged) {
        setQuery(singleDisplayValue);
      }
      lastSyncedSingleDisplayRef.current = singleDisplayValue;
    }
  }, [isOpen, props.mode, singleDisplayValue]);

  useEffect(() => {
    function handlePointerDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
        if (props.mode !== "multi") {
          setQuery(singleDisplayValue);
        }
      }
    }
    if (!isOpen) return;
    window.addEventListener("mousedown", handlePointerDown);
    return () => window.removeEventListener("mousedown", handlePointerDown);
  }, [isOpen, props.mode, singleDisplayValue]);

  const searchPath =
    isOpen && deferredQuery
      ? `/catalog/search?q=${encodeURIComponent(deferredQuery)}&types=${encodeURIComponent(
          allowedTypes.join(",")
        )}`
      : null;

  const { data, error, isLoading } = useSWR(
    searchPath,
    (path: string) => apiGet<CatalogSearchResponse>(path)
  );

  const availableResults = useMemo(() => {
    const selectedKeys = new Set(selectedItems.map((item) => resultKey(item)));
    const base =
      deferredQuery.length > 0
        ? data?.results ?? []
        : recentSelections.filter((item) => allowedTypes.includes(item.entity_type));
    return base.filter((item) =>
      props.mode === "multi" ? !selectedKeys.has(resultKey(item)) : true
    );
  }, [allowedTypes, data?.results, deferredQuery.length, props.mode, recentSelections, selectedItems]);

  const groupedResults = useMemo(
    () => groupResults(availableResults, allowedTypes),
    [allowedTypes, availableResults]
  );
  const flatResults = useMemo(
    () => groupedResults.flatMap((group) => group.items),
    [groupedResults]
  );

  useEffect(() => {
    setHighlightedIndex(flatResults.length > 0 ? 0 : -1);
  }, [deferredQuery, flatResults.length, isOpen]);

  function rememberSelection(result: CatalogSearchResult) {
    const deduped = [
      result,
      ...recentSelections.filter((entry) => resultKey(entry) !== resultKey(result)),
    ];
    setRecentSelections(deduped.slice(0, RECENT_LIMIT));
    saveRecentSelections(recentKey, deduped);
  }

  function handleSelect(result: CatalogSearchResult) {
    rememberSelection(result);
    if (props.mode === "multi") {
      props.onChange([...props.value, result]);
      setQuery("");
      setIsOpen(true);
      return;
    }
    props.onChange(result);
    setQuery(result.display_label);
    setIsOpen(false);
  }

  function handleClear() {
    if (props.mode === "multi") {
      props.onChange([]);
      setQuery("");
      return;
    }
    props.onChange(null);
    setQuery("");
    setIsOpen(false);
  }

  function removeMultiSelection(result: CatalogSearchResult) {
    if (props.mode !== "multi") return;
    props.onChange(props.value.filter((entry) => resultKey(entry) !== resultKey(result)));
  }

  function dismissPicker(event?: {
    preventDefault: () => void;
    stopPropagation: () => void;
  }) {
    event?.preventDefault();
    event?.stopPropagation();
    setIsOpen(false);
    if (props.mode !== "multi") {
      setQuery(singleDisplayValue);
      return;
    }
    setQuery("");
  }

  function handleRootKeyDownCapture(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (!isOpen || event.key !== "Escape") return;
    dismissPicker(event);
  }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!isOpen) {
        setIsOpen(true);
        return;
      }
      if (flatResults.length > 0) {
        setHighlightedIndex((prev) => (prev + 1) % flatResults.length);
      }
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!isOpen) {
        setIsOpen(true);
        return;
      }
      if (flatResults.length > 0) {
        setHighlightedIndex((prev) => (prev <= 0 ? flatResults.length - 1 : prev - 1));
      }
      return;
    }
    if (event.key === "Enter" && isOpen && highlightedIndex >= 0 && flatResults[highlightedIndex]) {
      event.preventDefault();
      handleSelect(flatResults[highlightedIndex]);
      return;
    }
    if (event.key === "Escape") {
      dismissPicker(event);
    }
  }

  const panelClassName =
    presentation === "inline"
      ? "mt-2 rounded-2xl border border-slate-200 bg-white shadow-panel"
      : "absolute left-0 right-0 top-full z-30 mt-2 rounded-2xl border border-slate-200 bg-white shadow-panel";

  return (
    <div className="relative" ref={rootRef} onKeyDownCapture={handleRootKeyDownCapture}>
      {props.mode === "multi" && props.value.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-2">
          {props.value.map((item) => (
            <button
              key={resultKey(item)}
              className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-700"
              onClick={() => removeMultiSelection(item)}
              type="button"
            >
              <span>{item.display_label}</span>
              <span className="text-slate-400">x</span>
            </button>
          ))}
        </div>
      )}
      <div className="flex items-center gap-2">
        <input
          className="input"
          disabled={disabled}
          onChange={(event) => {
            const nextValue = event.target.value;
            setQuery(nextValue);
            onQueryChange?.(nextValue);
            setIsOpen(true);
          }}
          onFocus={() => setIsOpen(true)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder ?? "Search catalog"}
          value={query}
        />
        {(props.mode === "multi" ? props.value.length > 0 : !!selectedSingle || query.trim()) && (
          <button
            className="button-subtle shrink-0"
            onClick={() => {
              handleClear();
              onQueryChange?.("");
            }}
            type="button"
          >
            Clear
          </button>
        )}
      </div>
      {isOpen && (
        <div className={panelClassName}>
          <div className="max-h-80 overflow-y-auto p-2">
            {!deferredQuery && recentSelections.length > 0 && (
              <p className="px-2 pb-2 pt-1 text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">
                Recent Selections
              </p>
            )}
            {isLoading && <p className="px-2 py-3 text-sm text-slate-500">Searching…</p>}
            {!isLoading && error && (
              <p className="px-2 py-3 text-sm text-red-600">{String(error)}</p>
            )}
            {!isLoading && !error && groupedResults.length === 0 && (
              <p className="px-2 py-3 text-sm text-slate-500">
                {deferredQuery ? "No matches found." : "Type to search or use a recent selection."}
              </p>
            )}
            {!isLoading &&
              !error &&
              groupedResults.map((group) => {
                let localIndexOffset = 0;
                const priorCount = groupedResults
                  .filter((candidate) => allowedTypes.indexOf(candidate.type) < allowedTypes.indexOf(group.type))
                  .reduce((total, candidate) => total + candidate.items.length, 0);
                return (
                  <div key={group.type} className="pb-2 last:pb-0">
                    <p className="px-2 pb-1 pt-1 text-xs font-semibold uppercase tracking-[0.12em] text-slate-400">
                      {group.label}
                    </p>
                    <div className="space-y-1">
                      {group.items.map((item) => {
                        const itemIndex = priorCount + localIndexOffset;
                        localIndexOffset += 1;
                        const isHighlighted = itemIndex === highlightedIndex;
                        return (
                          <button
                            key={resultKey(item)}
                            className={`flex w-full flex-col rounded-xl px-3 py-2 text-left transition ${
                              isHighlighted ? "bg-signal/10 text-signal" : "hover:bg-slate-50"
                            }`}
                            onClick={() => handleSelect(item)}
                            onMouseDown={(event) => event.preventDefault()}
                            type="button"
                          >
                            <span className="text-sm font-semibold">{item.display_label}</span>
                            {item.summary && (
                              <span className="text-xs text-slate-500">{item.summary}</span>
                            )}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
          </div>
        </div>
      )}
    </div>
  );
}
