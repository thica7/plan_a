import type { AnalysisPlanTask } from "../../api/types";
import { useTranslation } from "../../stores/i18n";
import { displayLabel } from "../../i18n/display";
import { MetricValue } from "./MetricValue";
import {
  summarizeTaskStages,
  taskPriorityClass,
  taskPriorityRank,
} from "./utils";

export function TaskDecompositionPanel({ tasks }: { tasks: AnalysisPlanTask[] }) {
  const { locale, t } = useTranslation();
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
        <h2>{t('tasks.title')}</h2>
        <span className="muted-text">{tasks.length} {t('tasks.count')}</span>
      </div>
      <div className="metric-grid compact">
        <MetricValue label={t('tasks.collector')} value={String(stageCounts.collector ?? 0)} />
        <MetricValue label={t('tasks.analyst')} value={String(stageCounts.analyst ?? 0)} />
        <MetricValue label={t('tasks.research')} value={String(stageCounts.survey_interview ?? 0)} />
        <MetricValue label={t('tasks.highPriority')} value={String(highPriorityCount)} />
      </div>
      <div className="project-meta-row">
        <span>{t('tasks.maxTurns')} {maxTurnBudget}</span>
        <span>{t('tasks.stages')} {Object.keys(stageCounts).length}</span>
      </div>
      {watchTasks.length > 0 ? (
        <div className="recommendation-list compact">
          {watchTasks.map((task) => (
            <article className={`recommendation-card ${taskPriorityClass(task.priority)}`} key={task.id}>
              <strong>{displayLabel(task.stage, locale)}</strong>
              <span>
                {task.competitor ?? t('tasks.allCompetitors')} / {displayLabel(task.dimension, locale)} / {displayLabel(task.priority, locale)}
              </span>
              <p>{task.reason}</p>
              <div className="project-meta-row">
                <span>{t('tasks.turns')} {task.max_turns}</span>
                <span>{t('tasks.deps')} {task.depends_on.length}</span>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="muted-text">{t('tasks.noTasks')}</p>
      )}
    </aside>
  );
}
