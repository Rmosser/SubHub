/* Why a pull failed, one line per failed attempt: client, status, the host it tried (mono, truncated, full text in the title). */
import type { PullReason } from "@/pages/Sources/sourceHealth";

interface Props {
  reasons: PullReason[];
  ariaLabel: string;
  children?: React.ReactNode;
}

export function ReasonTable({ reasons, ariaLabel, children }: Props) {
  return (
    <dl className="s-reasons" aria-label={ariaLabel}>
      {reasons.map((reason, index) => (
        <div key={`${reason.client}-${index}`} className={reason.client ? undefined : "wide"}>
          {reason.client ? <dt>{reason.client}</dt> : null}
          <dd className="status" title={reason.status}>{reason.status}</dd>
          {reason.client ? <dd className="host" title={reason.host || undefined}>{reason.host}</dd> : null}
        </div>
      ))}
      {children ? <div className="extra">{children}</div> : null}
    </dl>
  );
}
