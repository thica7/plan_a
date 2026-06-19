import { Languages } from "lucide-react";
import { useTranslation } from "../../stores/i18n";
import { SectionHeading } from "./SectionHeading";
import type { OutputLanguage } from "./types";

interface OutputLanguageSectionProps {
  outputLanguage: OutputLanguage;
  setOutputLanguage: (language: OutputLanguage) => void;
}

export function OutputLanguageSection({
  outputLanguage,
  setOutputLanguage,
}: OutputLanguageSectionProps) {
  const { t } = useTranslation();
  return (
    <section className="form-section execution-section">
      <SectionHeading
        icon={<Languages size={17} aria-hidden />}
        index="06"
        meta={t("newRun.outputLanguageDesc")}
        title={t("newRun.outputLanguage")}
      />
      <div className="execution-mode-grid" role="radiogroup" aria-label={t("newRun.outputLanguage")}>
        <button
          className={outputLanguage === "zh-CN" ? "execution-mode-card active" : "execution-mode-card"}
          onClick={() => setOutputLanguage("zh-CN")}
          type="button"
        >
          <Languages size={18} aria-hidden />
          <span>
            <strong>{t("newRun.outputChinese")}</strong>
            <em>{t("newRun.outputChineseDesc")}</em>
          </span>
          <i aria-hidden />
        </button>
        <button
          className={outputLanguage === "en-US" ? "execution-mode-card active" : "execution-mode-card"}
          onClick={() => setOutputLanguage("en-US")}
          type="button"
        >
          <Languages size={18} aria-hidden />
          <span>
            <strong>{t("newRun.outputEnglish")}</strong>
            <em>{t("newRun.outputEnglishDesc")}</em>
          </span>
          <i aria-hidden />
        </button>
      </div>
    </section>
  );
}
