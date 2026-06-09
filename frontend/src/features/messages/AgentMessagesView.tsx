import type { AgentMessage, ToolCallMessage } from "../../api/types";
import { useTranslation } from '../../stores/i18n';

interface Props {
  messages: AgentMessage[];
  toolCalls: ToolCallMessage[];
}

export function AgentMessagesView({ messages, toolCalls }: Props) {
  const {t}=useTranslation();
  const consumed = messages.filter((message) => message.status === "consumed").length;
  const queued = messages.length - consumed;

  return (
    <section className="panel agent-messages-panel">
      <div className="panel-heading-row">
        <h2>{t('messages.title')}</h2>
        <span className="muted-text">
          {messages.length} messages / {consumed} consumed / {queued} queued / {toolCalls.length} tool calls
        </span>
      </div>
      {messages.length === 0 ? (
        <p>{t('messages.noMessages')}</p>
      ) : (
        <div className="agent-message-list">
          {messages.slice(-18).map((message) => (
            <article key={message.id}>
              <div className="message-route">
                <strong>{message.from_agent} -&gt; {message.to_agent}</strong>
                <code className={`message-status ${message.status}`}>{message.status}</code>
              </div>
              <span>{message.message_type}</span>
              <code>{message.payload_schema}</code>
              {message.consumed_by ? <em>consumed by {message.consumed_by}</em> : null}
              {message.source_message_ids.length > 0 ? (
                <small>from {message.source_message_ids.join(", ")}</small>
              ) : null}
            </article>
          ))}
        </div>
      )}
      {toolCalls.length > 0 ? (
        <div className="tool-message-list">
          <h3>{t('messages.toolCalls')}</h3>
          {toolCalls.slice(-10).map((call) => (
            <article key={call.id}>
              <strong>{call.agent}{call.subagent ? `:${call.subagent}` : ""}</strong>
              <span>{call.tool_name}</span>
              <code>{call.status}</code>
              {call.source_message_id ? <small>message {call.source_message_id}</small> : null}
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}
