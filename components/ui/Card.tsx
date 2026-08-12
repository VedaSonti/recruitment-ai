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
        "rounded-2xl border border-slate-100 bg-white shadow-soft",
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
        <h2 className="font-display text-[20px] font-bold leading-6 tracking-[-0.02em] text-slate-900">
          {title}
        </h2>
        {subtitle ? (
          <p className="mt-1 text-[14px] leading-5 text-slate-500">{subtitle}</p>
        ) : null}
      </div>
      {action}
    </div>
  );
}
