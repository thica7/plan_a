import type { AgentMessage, ToolCallMessage } from "../../api/types";
import { useTranslation } from '../../stores/i18n';
import { displayLabel, displayScope } from "../../i18n/display";
import { formatModuleExecutionStatus } from "../trace/traceModel";

interface Props {
  messages: AgentMessage[];
  toolCalls: ToolCallMessage[];
}

export function AgentMessagesView({ messages, toolCalls }: Props) {
  const { locale, t } = useTranslation();
  const consumed = messages.filter((message) => message.status === "consumed").length;
  const queued = messages.length - consumed;

  return (
    <section className="panel agent-messages-panel">
      <div className="panel-heading-row">
        <h2>{t('messages.title')}</h2>
        <span className="muted-text">
          {messages.length} {t('messages.count')} / {consumed} {t('messages.consumed')} / {queued} {t('messages.queued')} / {toolCalls.length} {t('messages.toolCallCount')}
        </span>
      </div>
      {messages.length === 0 ? (
        <p>{t('messages.noMessages')}</p>
      ) : (
        <div className="agent-message-list">
          {messages.slice(-18).map((message) => {
            const moduleStatus = formatModuleExecutionStatus(message.payload, locale);
            return (
              <article key={message.id}>
                <div className="message-route">
                  <strong>{displayLabel(message.from_agent, locale)} -&gt; {displayLabel(message.to_agent, locale)}</strong>
                  <code className={`message-status ${message.status}`}>{displayLabel(message.status, locale)}</code>
                </div>
                <span>{displayLabel(message.message_type, locale)}</span>
                <code>{message.payload_schema}</code>
                {moduleStatus ? <small>{moduleStatus}</small> : null}
                {message.consumed_by ? <em>{t('messages.consumedBy')} {displayLabel(message.consumed_by, locale)}</em> : null}
                {message.source_message_ids.length > 0 ? (
                  <small>{t('messages.from')} {message.source_message_ids.join(", ")}</small>
                ) : null}
              </article>
            );
          })}
        </div>
      )}
      {toolCalls.length > 0 ? (
        <div className="tool-message-list">
          <h3>{t('messages.toolCalls')}</h3>
          {toolCalls.slice(-10).map((call) => (
            <article key={call.id}>
              <strong>{displayLabel(call.agent, locale)}{call.subagent ? `:${displayScope(call.subagent, locale)}` : ""}</strong>
              <span>{displayLabel(call.tool_name, locale)}</span>
              <code>{displayLabel(call.status, locale)}</code>
              {call.source_message_id ? <small>{t('messages.message')} {call.source_message_id}</small> : null}
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}
