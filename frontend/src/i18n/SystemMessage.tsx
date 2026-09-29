import { useTranslation } from "../stores/i18n";
import { runtimeDiagnostic } from "./display";

/** Only for backend/system diagnostics. Research prose and evidence must remain verbatim. */
export function SystemMessage({ message }: { message: string }) {
  const { locale, t } = useTranslation();
  const translated = runtimeDiagnostic(message, locale);
  const untranslated = locale === "zh-CN" && translated === message && /^[A-Za-z]/.test(message);
  return (
    <span title={`${t('runtime.original')}：${message}`}>
      {untranslated ? `${t('runtime.original')}：${message}` : translated}
    </span>
  );
}
