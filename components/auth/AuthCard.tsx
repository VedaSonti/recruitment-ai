import type { ReactNode } from "react";
import Link from "next/link";

export function AuthCard({
  children,
  eyebrow,
  title,
  description,
}: {
  children: ReactNode;
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <main className="app-bg relative flex min-h-screen items-center justify-center overflow-hidden px-5 py-10 text-slate-900">
      <div className="pointer-events-none absolute -right-24 -top-24 h-96 w-96 rounded-full bg-brand/10 blur-3xl" />
      <div className="relative w-full max-w-[470px] rounded-2xl border border-slate-100 bg-white px-6 py-8 shadow-lift sm:px-10 sm:py-10">
        <Link aria-label="iSOFT Recruitment sign in" className="inline-flex items-center gap-3" href="/sign-in">
          <span className="font-display text-[28px] font-black leading-none tracking-[-0.08em] text-brand">iSOFT</span>
          <span className="h-6 w-px bg-brand/20" />
          <span className="font-display text-[16px] font-bold text-slate-900">Recruitment</span>
        </Link>
        <div className="mt-9">
          <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-brand">{eyebrow}</p>
          <h1 className="mt-3 font-display text-[32px] font-bold tracking-[-0.04em]">{title}</h1>
          <p className="mt-3 text-[14px] leading-6 text-slate-500">{description}</p>
        </div>
        <div className="mt-7">{children}</div>
      </div>
    </main>
  );
}
