import {
  Briefcase,
  Database,
  FileText,
  History,
  Layers,
  PlusCircle,
  ShieldCheck,
} from "lucide-react";

export const navItems = [
  { to: "/", label: "New run", icon: PlusCircle, end: true },
  { to: "/history", label: "Runs", icon: History },
  { to: "/enterprise", label: "Workbench", icon: Briefcase },
  { to: "/competitors", label: "Competitors", icon: Layers },
  { to: "/evidence", label: "Evidence", icon: Database },
  { to: "/reports", label: "Reports", icon: FileText },
  { to: "/governance", label: "Governance", icon: ShieldCheck },
];

export function routeTitle(pathname: string) {
  if (pathname === "/") return "Run setup";
  if (pathname.startsWith("/runs/")) return "Run detail";
  if (pathname.startsWith("/history")) return "Run history";
  if (pathname.startsWith("/competitors")) return "Competitor library";
  if (pathname.startsWith("/evidence")) return "Evidence center";
  if (pathname.startsWith("/reports")) return "Report studio";
  if (pathname.startsWith("/governance")) return "Governance";
  if (pathname.startsWith("/enterprise")) return "Enterprise workbench";
  return "Workspace";
}
