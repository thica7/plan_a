import { UsersRound } from "lucide-react";
import { useTranslation } from "../../stores/i18n";
import { SectionHeading } from "./SectionHeading";
import type { CollaborationMode } from "./types";

export function CollaborationSection({
  collaborationMode,
  setCollaborationMode,
}: {
  collaborationMode: CollaborationMode;
  setCollaborationMode: (mode: CollaborationMode) => void;
}) {
  const { t } = useTranslation();
  return (
    <section className="form-section collaboration-section">
      <SectionHeading
        icon={<UsersRound size={17} aria-hidden />}
        index="09"
        meta={t("newRun.collaborationDesc")}
        title={t("newRun.collaboration")}
      />
      <div className="collaboration-grid" role="group" aria-label={t("newRun.collaboration")}>
        {(["ai", "assisted"] as const).map((mode) => (
          <button
            aria-pressed={collaborationMode === mode}
            className={collaborationMode === mode ? "collaboration-card active" : "collaboration-card"}
            data-action-audit="local"
            data-action-id={`new-run.collaboration.${mode}`}
            key={mode}
            onClick={() => setCollaborationMode(mode)}
            type="button"
          >
            <strong>{t(`newRun.collaboration.${mode}`)}</strong>
            <span>{t(`newRun.collaboration.${mode}Desc`)}</span>
          </button>
        ))}
      </div>
    </section>
  );
}
