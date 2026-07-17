import { cx } from "@/src/lib/utils";

export function ProgressBar({
  className,
  value,
}: {
  className?: string;
  value: number;
}) {
  const clamped = Math.max(0, Math.min(100, Math.round(value)));
  const color =
    clamped >= 80
      ? "bg-[#06c95e]"
      : clamped >= 60
        ? "bg-[#f6b800]"
        : "bg-[#ef4444]";

  return (
    <div className={cx("h-2 overflow-hidden rounded-full bg-[#edf0f4]", className)}>
      <div className={cx("h-full rounded-full", color)} style={{ width: `${clamped}%` }} />
    </div>
  );
}
