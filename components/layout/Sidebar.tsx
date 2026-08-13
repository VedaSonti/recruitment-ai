"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  BriefcaseBusiness,
  ClipboardCheck,
  Database,
  FileUp,
  LayoutDashboard,
  Send,
  Sparkles,
  Trophy,
  LogOut,
  Users,
} from "lucide-react";
import { PersonaLogo } from "@/components/branding/PersonaLogo";
import { getJobs, logoutRecruiter, type RecruiterUser } from "@/src/lib/api";
import { getJobId } from "@/src/lib/utils";

const navItems = [
  { label: "Dashboard", href: "/", icon: LayoutDashboard, active: ["/"] },
  { label: "Upload Job", href: "/upload-job", icon: FileUp, active: ["/upload-job"] },
  { label: "Upload CVs", href: "/upload-cvs", icon: Users, active: ["/upload-cvs"] },
  { label: "Match Results", href: "/matches", icon: Sparkles, active: ["/matches"] },
  {
    label: "Candidate Review",
    href: "/candidate-review",
    icon: ClipboardCheck,
    active: ["/candidate-review"],
  },
  { label: "Top Candidates", href: "/top-candidates", icon: Trophy, active: ["/top-candidates"] },
  { label: "Profile Uplifting", href: "/uplift", icon: BriefcaseBusiness, active: ["/uplift"] },
  { label: "Client Delivery", href: "/delivery", icon: Send, active: ["/delivery"] },
];

export function Sidebar({ recruiter }: { recruiter: RecruiterUser | null }) {
  const pathname = usePathname();
  const router = useRouter();
  const [firstJobId, setFirstJobId] = useState("");
  const [notice, setNotice] = useState("");
  const [isSigningOut, setIsSigningOut] = useState(false);

  async function signOut() {
    if (isSigningOut) return;
    setIsSigningOut(true);
    try {
      await logoutRecruiter();
    } finally {
      router.replace("/sign-in");
      router.refresh();
    }
  }

  useEffect(() => {
    getJobs()
      .then((jobs) => setFirstJobId(getJobId(jobs[0] ?? {})))
      .catch(() => setFirstJobId(""));
  }, []);

  useEffect(() => {
    if (!notice) {
      return;
    }

    const timer = window.setTimeout(() => setNotice(""), 2600);
    return () => window.clearTimeout(timer);
  }, [notice]);

  return (
    <aside className="sidebar-bg flex h-screen w-[252px] shrink-0 flex-col text-white shadow-2xl shadow-slate-950/20">
      <div className="border-b border-white/10 px-6 py-7">
        <PersonaLogo className="w-full max-w-[196px]" priority tone="onDark" />
      </div>

      <nav className="flex-1 space-y-1.5 overflow-y-auto px-3 py-5">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive =
            item.active.includes(pathname) ||
            item.active.some((path) => path !== "/" && pathname.startsWith(path));
          const href =
            item.label === "Match Results" && firstJobId
              ? `/matches/${encodeURIComponent(firstJobId)}`
              : item.href;

          return (
            <Link
              className={`flex h-11 items-center gap-3 rounded-xl px-4 text-[14px] font-medium transition duration-200 ${
                isActive ? "nav-active font-semibold" : "text-white/60 hover:bg-white/[0.07] hover:text-white"
              }`}
              href={href}
              key={item.label}
              onClick={(event) => {
                if (item.label === "Match Results" && !firstJobId) {
                  event.preventDefault();
                  setNotice("Upload a job description first to view match results");
                }
              }}
            >
              <Icon className="h-[18px] w-[18px]" strokeWidth={1.8} />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {notice ? (
        <div className="mx-4 mb-3 rounded-xl border border-brand/20 bg-white px-3 py-2 text-[12px] font-bold text-brand-dark shadow-soft">
          {notice}
        </div>
      ) : null}

      <div className="border-t border-white/10 p-4">
        {recruiter ? (
          <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/[0.07] p-3.5 backdrop-blur-sm">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand text-[13px] font-bold shadow-lg shadow-brand/20">
              {recruiter.full_name.split(/\s+/).map((part) => part[0]).join("").slice(0, 2).toUpperCase()}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-[14px] font-bold">{recruiter.full_name}</p>
              <p className="truncate text-[12px] text-white/80">{recruiter.email}</p>
            </div>
            <button aria-label="Sign out" className="rounded p-2 text-white/75 transition hover:bg-white/10 hover:text-white disabled:opacity-50" disabled={isSigningOut} onClick={signOut} title="Sign out" type="button"><LogOut className="h-4 w-4" /></button>
          </div>
        ) : (
          <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/[0.07] p-3.5 backdrop-blur-sm">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand text-[13px] font-bold shadow-lg shadow-brand/20">SJ</span>
            <div><p className="text-[14px] font-bold">Sarah Johnson</p><p className="text-[12px] text-white/80">Senior Recruiter</p></div>
          </div>
        )}
      </div>
    </aside>
  );
}
