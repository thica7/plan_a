import type { EnterpriseView } from "./types";

export const workbenchViewRoutes: Record<EnterpriseView, string> = {
  overview: "/enterprise",
  evidence: "/evidence",
  reports: "/reports",
  competitors: "/competitors",
  governance: "/governance",
  activity: "/activity",
};
