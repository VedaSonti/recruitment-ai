"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BriefcaseBusiness,
  ClipboardCheck,
  Database,
  FileUp,
  LayoutDashboard,
  Send,
  Sparkles,
  Trophy,
  Upload,
  Users,
} from "lucide-react";
import { getJobs } from "@/src/lib/api";
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

export function Sidebar() {
  const pathname = usePathname();
  const [firstJobId, setFirstJobId] = useState("");
  const [notice, setNotice] = useState("");

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
    <aside className="flex h-screen w-[252px] shrink-0 flex-col bg-crimson-800 text-white">
      <div className="border-b border-white/10 px-6 py-7">
        <div className="flex items-center gap-3">
          <span className="text-[30px] font-black leading-none tracking-[-0.08em] text-[#ff1717]">
            iSOFT
          </span>
          <span className="text-[20px] font-bold">Recruitment</span>
        </div>
        <p className="mt-2 text-[13px] text-white/80">AI-Powered Matching</p>
      </div>

      <nav className="flex-1 space-y-2 overflow-y-auto px-4 py-5">
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
              className={`flex h-12 items-center gap-3 rounded-[8px] px-4 text-[16px] transition ${
                isActive ? "bg-[#ff1717] font-bold" : "text-white/90 hover:bg-white/10"
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
              <Icon className="h-5 w-5" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      {notice ? (
        <div className="mx-4 mb-3 rounded-[8px] bg-white px-3 py-2 text-[12px] font-bold text-crimson-700">
          {notice}
        </div>
      ) : null}

      <div className="border-t border-white/10 p-4">
        <div className="flex items-center gap-3 rounded-[8px] bg-white/12 p-4">
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-[#ff1717]">
            <Upload className="h-5 w-5 rotate-180" />
          </span>
          <div>
            <p className="text-[14px] font-bold">Sarah Johnson</p>
            <p className="text-[12px] text-white/80">Senior Recruiter</p>
          </div>
        </div>
      </div>
    </aside>
  );
}
