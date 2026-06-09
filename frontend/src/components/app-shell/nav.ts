import {
  Bell,
  Briefcase,
  Database,
  FileText,
  History,
  type LucideIcon,
  Layers,
  PlusCircle,
  ShieldCheck,
} from "lucide-react";

export interface ShellNavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

export interface ShellNavGroup {
  label: string;
  items: ShellNavItem[];
}

export const navGroups: ShellNavGroup[] = [
  {
    label: "Research",
    items: [
      { to: "/", label: "New Run", icon: PlusCircle, end: true },
      { to: "/history", label: "Runs", icon: History },
      { to: "/enterprise", label: "Workbench", icon: Briefcase },
    ],
  },
  {
    label: "Evidence",
    items: [
      { to: "/evidence", label: "Sources", icon: Database },
      { to: "/reports", label: "Reports", icon: FileText },
    ],
  },
  {
    label: "Analysis",
    items: [
      { to: "/competitors", label: "Competitors", icon: Layers },
      { to: "/activity", label: "Activity", icon: Bell },
    ],
  },
  {
    label: "Quality",
    items: [
      { to: "/governance", label: "Governance", icon: ShieldCheck },
    ],
  },
];

export const navItems = navGroups.flatMap((group) => group.items);

export function routeTitle(pathname: string) {
  if (pathname === "/") return "Run setup";
  if (pathname.startsWith("/runs/")) return "Run detail";
  if (pathname.startsWith("/history")) return "Run history";
  if (pathname.startsWith("/competitors")) return "Competitor library";
  if (pathname.startsWith("/evidence")) return "Evidence center";
  if (pathname.startsWith("/reports")) return "Report studio";
  if (pathname.startsWith("/governance")) return "Governance";
  if (pathname.startsWith("/activity")) return "Activity center";
  if (pathname.startsWith("/enterprise")) return "Enterprise workbench";
  return "Workspace";
}
