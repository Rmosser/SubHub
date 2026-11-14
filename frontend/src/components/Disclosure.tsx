/* A section that stays folded on the glass: the etched title, a one-line summary on the right, the content on a plate below. */
import { useId, useState } from "react";

interface Props {
  title: string;
  summary?: React.ReactNode;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

export function Disclosure({ title, summary, defaultOpen = false, children }: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const panel = useId();
  return (
    <section className="s-disc">
      <button type="button" className="s-disc-btn" aria-expanded={open} aria-controls={panel} onClick={() => setOpen((value) => !value)}>
        <span className="s-disc-title">{title}</span>
        {summary ? <span className="s-disc-sum">{summary}</span> : <span />}
        <svg className="s-chev" viewBox="0 0 10 6" aria-hidden="true"><path d="M1 1l4 4 4-4" /></svg>
      </button>
      <div className="s-plate s-disc-panel" id={panel} hidden={!open}>
        {children}
      </div>
    </section>
  );
}
