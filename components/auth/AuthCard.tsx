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
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#fbf9fa] px-5 py-10 text-[#333333]">
      <div className="pointer-events-none absolute -right-24 -top-24 h-96 w-96 rounded-full bg-[#F2E1E3] blur-3xl" />
      <div className="relative w-full max-w-[470px] rounded-[16px] border border-[#eadfe1] bg-white px-6 py-8 shadow-[0_24px_70px_rgba(92,13,27,0.10)] sm:px-10 sm:py-10">
        <Link aria-label="iSOFT Recruitment sign in" className="inline-flex items-center gap-3" href="/sign-in">
          <span className="text-[28px] font-black leading-none tracking-[-0.08em] text-[#E01111]">iSOFT</span>
          <span className="h-6 w-px bg-[#5C0D1B]/20" />
          <span className="text-[16px] font-bold text-[#333333]">Recruitment</span>
        </Link>
        <div className="mt-9">
          <p className="text-[12px] font-bold uppercase tracking-[0.16em] text-[#E01111]">{eyebrow}</p>
          <h1 className="mt-3 text-[32px] font-bold tracking-[-0.03em]">{title}</h1>
          <p className="mt-3 text-[14px] leading-6 text-[#6f7075]">{description}</p>
        </div>
        <div className="mt-7">{children}</div>
      </div>
    </main>
  );
}
