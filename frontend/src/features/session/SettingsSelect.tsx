import { useEffect, useRef, useState } from "react";

interface SettingsSelectProps<T extends string> {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  disabled: boolean;
  id: string;
}

export function SettingsSelect<T extends string>({ label, value, options, onChange, disabled, id }: SettingsSelectProps<T>) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const selected = options.find((option) => option.value === value);

  useEffect(() => {
    if (!open) return;
    const closeOnOutside = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutside);
    return () => document.removeEventListener("pointerdown", closeOnOutside);
  }, [open]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  return (
    <div
      className={`settings-select ${id}`}
      ref={root}
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape" && open) {
          event.preventDefault();
          event.stopPropagation();
          setOpen(false);
          trigger.current?.focus();
        } else if (open && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
          const buttons = [...(root.current?.querySelectorAll<HTMLButtonElement>(".settings-select-option") ?? [])];
          const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
          const next = (index + (event.key === "ArrowDown" ? 1 : buttons.length - 1)) % buttons.length;
          event.preventDefault();
          buttons[next]?.focus();
        }
      }}
    >
      <button
        ref={trigger}
        type="button"
        className="advanced-input settings-select-trigger"
        aria-label={`${label}，当前 ${selected?.label ?? value}`}
        aria-expanded={open}
        aria-controls={open ? `${id}-options` : undefined}
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            setOpen(true);
            requestAnimationFrame(() => {
              const buttons = root.current?.querySelectorAll<HTMLButtonElement>(".settings-select-option");
              buttons?.[event.key === "ArrowDown" ? 0 : buttons.length - 1]?.focus();
            });
          }
        }}
        disabled={disabled}
      >
        <span>{selected?.label ?? value}</span>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
      </button>
      {open && (
        <div id={`${id}-options`} className="settings-select-options" role="group" aria-label={`${label}选项`}>
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              className="settings-select-option"
              aria-pressed={option.value === value}
              onClick={() => {
                onChange(option.value);
                setOpen(false);
                trigger.current?.focus();
              }}
            >
              <span>{option.label}</span>
              {option.value === value && <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="m4 12 5 5L20 6" /></svg>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
