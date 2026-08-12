import type { ReactNode } from "react";
import { Card } from "@/components/ui/Card";
import { cx } from "@/src/lib/utils";

export function StatCard({
  accent = "crimson",
  icon,
  label,
  value,
}: {
  accent?: "crimson" | "green" | "amber" | "red";
  icon?: ReactNode;
  label: string;
  value: ReactNode;
}) {
  return (
    <Card className="px-6 py-5 transition duration-200 hover:-translate-y-0.5 hover:shadow-lift">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[13px] font-medium uppercase tracking-[0.06em] text-slate-500">{label}</p>
          <p className="mt-2 font-display text-[32px] font-bold leading-none tracking-[-0.04em] text-brand-dark">
            {value}
          </p>
        </div>
        <span
          className={cx(
            "flex h-8 w-8 items-center justify-center rounded-xl text-white shadow-sm",
            accent === "crimson" && "bg-brand",
            accent === "green" && "bg-[#06c95e]",
            accent === "amber" && "bg-[#ff6b00]",
            accent === "red" && "bg-[#ff1717]",
          )}
        >
          {icon}
        </span>
      </div>
    </Card>
  );
}
