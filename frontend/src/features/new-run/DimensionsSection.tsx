import { Gauge } from "lucide-react";
import type { ScenarioPack, SkillSpec } from "../../api/types";
import { useTranslation } from '../../stores/i18n';
import { isDimensionLocked } from "./dimensions";
import { SectionHeading } from "./SectionHeading";

interface DimensionsSectionProps {
  lockedDimensions: string[];
  selected: string[];
  selectedScenario: ScenarioPack | null;
  skills: SkillSpec[];
  toggleDimension: (skillName: string) => void;
}

export function DimensionsSection({
  lockedDimensions,
  selected,
  selectedScenario,
  skills,
  toggleDimension,
}: DimensionsSectionProps) {
  const { t } = useTranslation();
  return (
    <section className="form-section">
      <SectionHeading
        icon={<Gauge size={17} aria-hidden />}
        index="04"
        meta={`${selected.length} ${t('newRun.dimensionsDesc')}`}
        title={t('newRun.dimensions')}
      />
      <div className="skill-grid">
        {skills.map((skill) => {
          const active = selected.includes(skill.name);
          const locked = isDimensionLocked(skill.name, lockedDimensions);
          return (
            <button
              className={active ? "skill-tile active" : "skill-tile"}
              key={skill.name}
              type="button"
              onClick={() => toggleDimension(skill.name)}
            >
              <strong>{skill.name}</strong>
              <span>
                {locked
                  ? selectedScenario
                    ? `${skill.description} Required by selected ScenarioPack.`
                    : `${skill.description} Required schema dimension.`
                  : skill.description}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
