import { useMemo, useRef, useState } from "react";
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
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    const q = value.trim().toLowerCase();
    return q ? options.filter((opt) => opt.toLowerCase().includes(q)) : options;
  }, [options, value]);

  const showDropdown = isOpen && !disabled && filtered.length > 0;

  return (
    <PopoverPrimitive.Root open={showDropdown}>
      <PopoverPrimitive.Anchor asChild>
        <div className="relative" title={title}>
          <input
            ref={inputRef}
            className={`input${!disabled && options.length > 0 ? " !pr-7" : ""}`}
            value={value}
            onChange={(e) => {
              onChange(e.target.value);
              if (!isOpen) setIsOpen(true);
            }}
            onFocus={() => setIsOpen(true)}
            onBlur={() => {
              // Delay to allow click on dropdown item to fire first
              setTimeout(() => setIsOpen(false), 200);
            }}
            placeholder={placeholder}
            disabled={disabled}
          />
          {!disabled && options.length > 0 && (
            <button
              type="button"
              className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 transition hover:text-slate-600"
              onClick={() => {
                setIsOpen((prev) => !prev);
                inputRef.current?.focus();
              }}
              tabIndex={-1}
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
          {filtered.map((opt) => (
            <button
              key={opt}
              type="button"
              className={`w-full rounded-lg px-3 py-1.5 text-left text-sm transition ${
                opt === value
                  ? "bg-signal/10 font-semibold text-signal"
                  : "hover:bg-slate-50"
              }`}
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                onChange(opt);
                setIsOpen(false);
              }}
            >
              {opt}
            </button>
          ))}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}
