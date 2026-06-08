import { ListChecks } from "lucide-react";
import { starterPresets, type StarterPreset } from "./dimensions";
import { SectionHeading } from "./SectionHeading";

interface ScopeSectionProps {
  onPreset: (preset: StarterPreset) => void;
  scenarioId: string;
  setTopic: (topic: string) => void;
  topic: string;
}

export function ScopeSection({
  onPreset,
  scenarioId,
  setTopic,
  topic,
}: ScopeSectionProps) {
  return (
    <section className="form-section">
      <SectionHeading
        icon={<ListChecks size={17} aria-hidden />}
        index="01"
        meta="topic and starting preset"
        title="Scope"
      />
      <label className="field-block">
        Topic
        <input value={topic} onChange={(event) => setTopic(event.target.value)} />
      </label>
      <div className="preset-grid">
        {starterPresets.map((preset) => (
          <button
            className={`preset-tile${scenarioId === preset.scenarioId ? " active" : ""}`}
            key={preset.id}
            type="button"
            onClick={() => onPreset(preset)}
          >
            <strong>{preset.name}</strong>
            <span>{preset.competitorLayer} / {preset.scenarioId}</span>
            <small>{preset.competitors.join(", ")}</small>
          </button>
        ))}
      </div>
    </section>
  );
}
