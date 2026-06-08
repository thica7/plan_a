export function MetricValue({ label, value }: { label: string; value: string }) {
  return (
    <span>
      <i aria-hidden />
      <strong>{value}</strong>
      <em>{label}</em>
    </span>
  );
}
