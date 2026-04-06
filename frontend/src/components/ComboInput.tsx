import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Popover as PopoverPrimitive } from "radix-ui";

interface ComboInputProps {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  placeholder?: string;
  disabled?: boolean;
  title?: string;
}

export function ComboInput({
  value,
  onChange,
  options,
  placeholder,
  disabled,
  title,
}: ComboInputProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const blurTimeoutRef = useRef<number | null>(null);
  const listboxId = useId();

  const filtered = useMemo(() => {
    const q = value.trim().toLowerCase();
    return q ? options.filter((opt) => opt.toLowerCase().includes(q)) : options;
  }, [options, value]);

  const showDropdown = isOpen && !disabled && filtered.length > 0;
  const activeOptionId =
    showDropdown && highlightedIndex >= 0 && filtered[highlightedIndex]
      ? `${listboxId}-option-${highlightedIndex}`
      : undefined;

  useEffect(() => {
    if (!showDropdown) {
      setHighlightedIndex(-1);
      return;
    }
    setHighlightedIndex((prev) => {
      if (prev >= 0 && prev < filtered.length) return prev;
      return 0;
    });
  }, [filtered.length, showDropdown]);

  useEffect(() => {
    return () => {
      if (blurTimeoutRef.current != null) {
        window.clearTimeout(blurTimeoutRef.current);
      }
    };
  }, []);

  function closeDropdown() {
    if (blurTimeoutRef.current != null) {
      window.clearTimeout(blurTimeoutRef.current);
      blurTimeoutRef.current = null;
    }
    setIsOpen(false);
    setHighlightedIndex(-1);
  }

  function openDropdown() {
    if (disabled || filtered.length === 0) return;
    if (blurTimeoutRef.current != null) {
      window.clearTimeout(blurTimeoutRef.current);
      blurTimeoutRef.current = null;
    }
    setIsOpen(true);
    setHighlightedIndex((prev) => {
      if (prev >= 0 && prev < filtered.length) return prev;
      return 0;
    });
  }

  function selectOption(option: string) {
    onChange(option);
    closeDropdown();
  }

  return (
    <PopoverPrimitive.Root open={showDropdown}>
      <PopoverPrimitive.Anchor asChild>
        <div className="relative" title={title}>
          <input
            ref={inputRef}
            className={`input${!disabled && options.length > 0 ? " !pr-7" : ""}`}
            value={value}
            role="combobox"
            aria-autocomplete="list"
            aria-controls={listboxId}
            aria-expanded={showDropdown}
            aria-activedescendant={activeOptionId}
            onChange={(e) => {
              onChange(e.target.value);
              if (!isOpen) openDropdown();
            }}
            onFocus={() => openDropdown()}
            onBlur={() => {
              // Delay to allow pointer selection to complete first.
              blurTimeoutRef.current = window.setTimeout(() => {
                closeDropdown();
              }, 200);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                if (!showDropdown) {
                  openDropdown();
                  return;
                }
                setHighlightedIndex((prev) => (prev + 1) % filtered.length);
                return;
              }
              if (e.key === "ArrowUp") {
                e.preventDefault();
                if (!showDropdown) {
                  openDropdown();
                  return;
                }
                setHighlightedIndex((prev) => (prev <= 0 ? filtered.length - 1 : prev - 1));
                return;
              }
              if (e.key === "Enter" && showDropdown && highlightedIndex >= 0 && filtered[highlightedIndex]) {
                e.preventDefault();
                selectOption(filtered[highlightedIndex]);
                return;
              }
              if (e.key === "Escape") {
                e.preventDefault();
                closeDropdown();
              }
            }}
            placeholder={placeholder}
            disabled={disabled}
          />
          {!disabled && options.length > 0 && (
            <button
              type="button"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 transition hover:text-slate-600"
              onClick={() => {
                if (showDropdown) {
                  closeDropdown();
                } else {
                  openDropdown();
                }
                inputRef.current?.focus();
              }}
              tabIndex={-1}
              aria-label="Toggle suggestions"
            >
              <svg
                width="12"
                height="12"
                viewBox="0 0 12 12"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  d="M3 4.5L6 7.5L9 4.5"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
          )}
        </div>
      </PopoverPrimitive.Anchor>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          align="start"
          sideOffset={4}
          className="z-50 max-h-48 w-[var(--radix-popover-trigger-width)] overflow-y-auto rounded-xl border border-slate-200 bg-white p-1 shadow-lg"
          onOpenAutoFocus={(e) => e.preventDefault()}
          onCloseAutoFocus={(e) => e.preventDefault()}
        >
          <div role="listbox" id={listboxId}>
            {filtered.map((opt, index) => {
              const isHighlighted = index === highlightedIndex;
              return (
                <button
                  key={opt}
                  id={`${listboxId}-option-${index}`}
                  type="button"
                  role="option"
                  aria-selected={isHighlighted}
                  className={`w-full rounded-lg px-3 py-1.5 text-left text-sm transition ${
                    isHighlighted || opt === value
                      ? "bg-signal/10 font-semibold text-signal"
                      : "hover:bg-slate-50"
                  }`}
                  onMouseEnter={() => setHighlightedIndex(index)}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => selectOption(opt)}
                >
                  {opt}
                </button>
              );
            })}
          </div>
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
