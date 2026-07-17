import type { ReactNode } from "react";
import { cx } from "@/src/lib/utils";

export function Card({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cx(
        "rounded-[8px] border border-[#E5E7EB] bg-white shadow-soft",
        className,
      )}
    >
      {children}
    </section>
  );
}

export function CardHeader({
  action,
  className,
  subtitle,
  title,
}: {
  action?: ReactNode;
  className?: string;
  subtitle?: string;
  title: string;
}) {
  return (
    <div className={cx("flex items-start justify-between gap-4", className)}>
      <div>
        <h2 className="text-[20px] font-bold leading-6 text-[#333438]">
          {title}
        </h2>
        {subtitle ? (
          <p className="mt-1 text-[14px] leading-5 text-[#77777a]">{subtitle}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}
