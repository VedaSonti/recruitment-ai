"use client";

import { useEffect, useState, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Sidebar } from "@/components/layout/Sidebar";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { getCurrentRecruiter, type RecruiterUser } from "@/src/lib/api";

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [recruiter, setRecruiter] = useState<RecruiterUser | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const isAuthPage = ["/sign-in", "/forgot-password", "/reset-password"].includes(pathname);
  const isCandidateInterview = pathname.startsWith("/interview/");

  useEffect(() => {
    if (isAuthPage || isCandidateInterview) {
      setCheckingSession(false);
      return;
    }
    let mounted = true;
    getCurrentRecruiter()
      .then(({ user }) => {
        if (mounted) setRecruiter(user);
      })
      .catch(() => {
        if (mounted) router.replace("/sign-in");
      })
      .finally(() => {
        if (mounted) setCheckingSession(false);
      });
    return () => {
      mounted = false;
    };
  }, [isAuthPage, isCandidateInterview, router]);

  if (isAuthPage) {
    return <div className="app-bg min-h-screen">{children}</div>;
  }

  if (!isCandidateInterview && checkingSession) {
    return <div className="app-bg flex min-h-screen items-center justify-center"><LoadingSpinner size="lg" /></div>;
  }

  if (!isCandidateInterview && !recruiter) {
    return null;
  }

  return (
    <div className="app-bg flex h-screen overflow-hidden">
      <Sidebar recruiter={recruiter} />
      <main className="min-w-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
        <div className="mx-auto max-w-[1280px]">{children}</div>
      </main>
    </div>
  );
}
