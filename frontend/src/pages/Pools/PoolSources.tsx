import { useMemo } from "react";
import { useGorelaySources, useStandardSources } from "@/api/queries";
import { Chip } from "@/components/Chip";

// 节点池的来源：能对上订阅源时显示名称；对不上（来源已删、未加载完）时用等宽弱色的 ID 兜底。
function useSourceNames() {
  const standard = useStandardSources();
  const gorelay = useGorelaySources();
  return useMemo(() => {
    const names = new Map<string, string>();
    for (const source of standard.data ?? []) names.set(source.id, source.name);
    for (const source of gorelay.data ?? []) names.set(source.id, source.name);
    return names;
  }, [standard.data, gorelay.data]);
}

export function PoolSources({ sources }: { sources: Record<string, number> }) {
  const names = useSourceNames();
  const entries = Object.entries(sources);
  if (entries.length === 0) return <span className="s-muted">-</span>;
  return (
    <div className="s-chips">
      {entries.map(([id, count]) => {
        const name = names.get(id);
        return name ? (
          <Chip key={id}>{name} <span className="s-num s-muted">{count}</span></Chip>
        ) : (
          <Chip key={id} mono muted title={id}>{id} <span className="s-num">{count}</span></Chip>
        );
      })}
    </div>
  );
}
