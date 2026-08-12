import type { ReactNode } from "react";

export function PageHeader({
  actions,
  subtitle,
  title,
}: {
  actions?: ReactNode;
  subtitle?: string;
  title: string;
}) {
  return (
    <div className="mb-8 flex flex-wrap items-start justify-between gap-5">
      <div>
        <h1 className="font-display text-[32px] font-bold leading-[1.05] tracking-[-0.035em] text-slate-950 sm:text-[36px]">
          {title}
        </h1>
        {subtitle ? (
          <p className="mt-2.5 max-w-2xl text-[15px] leading-6 text-slate-500">{subtitle}</p>
        ) : null}
      </div>
      {actions}
    </div>
  );
}
