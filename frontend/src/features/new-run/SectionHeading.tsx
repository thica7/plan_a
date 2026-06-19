import type { ReactNode } from "react";

export function SectionHeading({
  icon,
  index,
  meta,
  title,
}: {
  icon: ReactNode;
  index: string;
  meta: string;
  title: string;
}) {
  return (
    <div className="section-heading">
      <span>{index}</span>
      <div className="section-heading-icon">{icon}</div>
      <div>
        <h2>{title}</h2>
        <p>{meta}</p>
      </div>
    </div>
  );
}
