import { useId, useState } from 'react';
import { useTranslation } from "../stores/i18n";
import { runtimeDiagnostic } from "./display";

/** Only for backend/system diagnostics. Research prose and evidence must remain verbatim. */
export function SystemMessage({ message }: { message: string }) {
  const { locale, t } = useTranslation();
  const [showOriginal, setShowOriginal] = useState(false);
  const originalId = useId();
  const translated = runtimeDiagnostic(message, locale);
  const untranslated = locale === "zh-CN" && translated === message && /[A-Za-z]/.test(message) && !/[\u3400-\u9fff]/.test(message);
  return (
    <span title={`${t('runtime.original')}：${message}`}>
      {untranslated ? <>
        <button
          type="button"
          className="link link-primary text-inherit"
          data-action-id="system-message.original.toggle"
          data-action-audit="local"
          aria-expanded={showOriginal}
          aria-controls={originalId}
          onClick={() => setShowOriginal((visible) => !visible)}
        >
          {t(showOriginal ? 'runtime.hideOriginal' : 'runtime.viewOriginal')}
        </button>
        {showOriginal ? <span id={originalId}> {message}</span> : null}
      </> : translated}
    </span>
  );
}
