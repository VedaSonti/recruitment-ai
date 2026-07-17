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
    <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-[32px] font-bold leading-none text-[#333438]">
          {title}
        </h1>
        {subtitle ? (
          <p className="mt-3 text-[16px] leading-6 text-[#77777a]">{subtitle}</p>
        ) : null}
      </div>
      {actions}
    </div>
  );
}
