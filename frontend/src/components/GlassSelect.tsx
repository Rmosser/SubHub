/* A select etched into the glass. The visible face is ours; the menu is the platform's own native menu. */
export interface GlassOption {
  value: string;
  label: string;
}

interface Props {
  value: string;
  options: GlassOption[];
  onChange(value: string): void;
  ariaLabel: string;
  placeholder?: string;
  disabled?: boolean;
  stretch?: boolean;
  className?: string;
}

export function GlassSelect({ value, options, onChange, ariaLabel, placeholder, disabled, stretch, className }: Props) {
  const current = options.find((o) => o.value === value);
  return (
    <label className={["glass-select", stretch ? "stretch" : "", disabled ? "disabled" : "", className ?? ""].filter(Boolean).join(" ")}>
      <span className={`glass-select-value${current ? "" : " ph"}`}>{current?.label ?? placeholder ?? ""}</span>
      <svg className="glass-select-caret" viewBox="0 0 10 6" aria-hidden="true"><path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
      <select aria-label={ariaLabel} value={current ? value : ""} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {current ? null : <option value="" disabled>{placeholder ?? ""}</option>}
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );
}
