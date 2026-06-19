import type { ReactNode } from "react";
import { AlertTriangle, CheckCircle2 } from "lucide-react";

export function RuntimeLine({ children, ok }: { children: ReactNode; ok: boolean }) {
  return (
    <p className={ok ? "runtime-ok" : "runtime-warn"}>
      {ok ? <CheckCircle2 size={14} aria-hidden /> : <AlertTriangle size={14} aria-hidden />}
      <span>{children}</span>
    </p>
  );
}
