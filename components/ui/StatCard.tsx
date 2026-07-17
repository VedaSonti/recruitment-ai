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
    <Card className="px-6 py-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[14px] leading-5 text-[#333438]">{label}</p>
          <p className="mt-2 text-[32px] font-bold leading-none text-crimson-700">
            {value}
          </p>
        </div>
        <span
          className={cx(
            "flex h-6 w-6 items-center justify-center rounded-full text-white",
            accent === "crimson" && "bg-crimson-700",
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
