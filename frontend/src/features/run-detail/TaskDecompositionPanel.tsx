import type { AnalysisPlanTask } from "../../api/types";
import { MetricValue } from "./MetricValue";
import {
  summarizeTaskStages,
  taskPriorityClass,
  taskPriorityRank,
} from "./utils";

export function TaskDecompositionPanel({ tasks }: { tasks: AnalysisPlanTask[] }) {
  const stageCounts = summarizeTaskStages(tasks);
  const watchTasks = [...tasks]
    .sort((left, right) => {
      const priorityDelta = taskPriorityRank(right.priority) - taskPriorityRank(left.priority);
      if (priorityDelta !== 0) return priorityDelta;
      if (right.max_turns !== left.max_turns) return right.max_turns - left.max_turns;
      return left.id.localeCompare(right.id);
    })
    .slice(0, 8);
  const highPriorityCount = tasks.filter((task) => task.priority === "high").length;
  const maxTurnBudget = tasks.reduce((total, task) => total + task.max_turns, 0);

  return (
    <aside className="qa-panel run-quality-panel">
      <div className="panel-heading-row">
        <h2>Task decomposition</h2>
        <span className="muted-text">{tasks.length} tasks</span>
      </div>
      <div className="metric-grid compact">
        <MetricValue label="Collector" value={String(stageCounts.collector ?? 0)} />
        <MetricValue label="Analyst" value={String(stageCounts.analyst ?? 0)} />
        <MetricValue label="Research" value={String(stageCounts.survey_interview ?? 0)} />
        <MetricValue label="High priority" value={String(highPriorityCount)} />
      </div>
      <div className="project-meta-row">
        <span>Max turns {maxTurnBudget}</span>
        <span>Stages {Object.keys(stageCounts).length}</span>
      </div>
      {watchTasks.length > 0 ? (
        <div className="recommendation-list compact">
          {watchTasks.map((task) => (
            <article className={`recommendation-card ${taskPriorityClass(task.priority)}`} key={task.id}>
              <strong>{task.stage}</strong>
              <span>
                {task.competitor ?? "all competitors"} / {task.dimension} / {task.priority}
              </span>
              <p>{task.reason}</p>
              <div className="project-meta-row">
                <span>Turns {task.max_turns}</span>
                <span>Deps {task.depends_on.length}</span>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="muted-text">No adaptive tasks have been planned yet.</p>
      )}
    </aside>
  );
}
