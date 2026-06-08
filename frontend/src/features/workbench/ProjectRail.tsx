import { Bell, Briefcase } from "lucide-react";
import type { NotificationRecord, ProjectRecord } from "../../api/types";
import { EmptyState, LoadingState, Panel } from "../../components/ui";
import { formatDate } from "./format";

export function ProjectRail({
  isLoading,
  notifications,
  onSelect,
  projects,
  selectedProjectId,
}: {
  isLoading: boolean;
  notifications: NotificationRecord[];
  onSelect: (projectId: string) => void;
  projects: ProjectRecord[];
  selectedProjectId: string | null;
}) {
  return (
    <aside className="project-rail redesigned-rail">
      <Panel title="Projects" icon={<Briefcase size={16} aria-hidden />}>
        {isLoading ? <LoadingState label="Loading projects" /> : null}
        {!isLoading && projects.length === 0 ? <EmptyState title="No projects found" /> : null}
        <div className="project-list">
          {projects.map((project) => (
            <button
              className={project.id === selectedProjectId ? "project-card active" : "project-card"}
              key={project.id}
              type="button"
              onClick={() => onSelect(project.id)}
            >
              <strong>{project.name}</strong>
              <span>{project.competitor_layer} / {project.scenario_id ?? "scenario auto"}</span>
              <em>{formatDate(project.updated_at)}</em>
            </button>
          ))}
        </div>
      </Panel>

      <Panel title="Signals" icon={<Bell size={16} aria-hidden />}>
        <div className="notification-list compact">
          {notifications.slice(0, 5).map((notification) => (
            <article className={`notification-item ${notification.severity}`} key={notification.id}>
              <strong>{notification.title}</strong>
              <span>{notification.status} / {formatDate(notification.created_at)}</span>
            </article>
          ))}
        </div>
        {notifications.length === 0 ? <p className="muted-line">No in-app notifications.</p> : null}
      </Panel>
    </aside>
  );
}
