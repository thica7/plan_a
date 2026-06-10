import {
  Bell,
  BookOpen,
  Briefcase,
  Database,
  FileText,
  History,
  type LucideIcon,
  Layers,
  PlusCircle,
  Search,
  ShieldCheck,
  Workflow,
} from "lucide-react";

export interface ShellNavItem {
  to: string;
  labelKey: string;
  icon: LucideIcon;
  end?: boolean;
}

export interface ShellNavGroup {
  labelKey: string;
  items: ShellNavItem[];
}

export const navGroups: ShellNavGroup[] = [
  {
    labelKey: "nav.research",
    items: [
      { to: "/", labelKey: "nav.newRun", icon: PlusCircle, end: true },
      { to: "/history", labelKey: "nav.runs", icon: History },
      { to: "/enterprise", labelKey: "nav.workbench", icon: Briefcase },
    ],
  },
  {
    labelKey: "nav.evidence",
    items: [
      { to: "/evidence", labelKey: "nav.sources", icon: Database },
      { to: "/knowledge", labelKey: "nav.knowledge", icon: BookOpen },
      { to: "/search", labelKey: "nav.search", icon: Search },
      { to: "/crawl", labelKey: "nav.crawl", icon: Workflow },
      { to: "/reports", labelKey: "nav.reports", icon: FileText },
    ],
  },
  {
    labelKey: "nav.analysis",
    items: [
      { to: "/competitors", labelKey: "nav.competitors", icon: Layers },
      { to: "/activity", labelKey: "nav.activity", icon: Bell },
    ],
  },
  {
    labelKey: "nav.quality",
    items: [
      { to: "/governance", labelKey: "nav.governance", icon: ShieldCheck },
    ],
  },
];

export const navItems = navGroups.flatMap((group) => group.items);

export function routeTitleKey(pathname: string) {
  if (pathname === "/") return "route.runSetup";
  if (pathname.startsWith("/runs/")) return "route.runDetail";
  if (pathname.startsWith("/history")) return "route.runHistory";
  if (pathname.startsWith("/knowledge")) return "route.knowledgeBase";
  if (pathname.startsWith("/search")) return "route.knowledgeSearch";
  if (pathname.startsWith("/crawl")) return "route.crawler";
  if (pathname.startsWith("/competitors")) return "route.competitorLibrary";
  if (pathname.startsWith("/evidence")) return "route.evidenceCenter";
  if (pathname.startsWith("/reports")) return "route.reportStudio";
  if (pathname.startsWith("/governance")) return "route.governance";
  if (pathname.startsWith("/activity")) return "route.activityCenter";
  if (pathname.startsWith("/enterprise")) return "route.enterpriseWorkbench";
  return "route.workspace";
}
