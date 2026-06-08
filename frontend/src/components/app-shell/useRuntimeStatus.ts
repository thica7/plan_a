import { useEffect, useState } from "react";
import { getRuntime } from "../../api/client";
import type { RuntimeConfig } from "../../api/types";

export function useRuntimeStatus() {
  const [runtime, setRuntime] = useState<RuntimeConfig | null>(null);

  useEffect(() => {
    let active = true;
    getRuntime()
      .then((value) => {
        if (active) setRuntime(value);
      })
      .catch(() => {
        if (active) setRuntime(null);
      });
    return () => {
      active = false;
    };
  }, []);

  const systemReady =
    runtime?.temporal_cutover_ready &&
    ((runtime.has_ark_api_key && runtime.has_ark_model) ||
      (runtime.has_backup_llm_api_key && runtime.has_backup_llm_model));

  return {
    runtime,
    systemReady: Boolean(systemReady),
    temporalRouted: Boolean(runtime?.temporal_cutover_ready),
  };
}
