"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowRight,
  CheckCircle2,
  Eye,
  EyeOff,
  LockKeyhole,
  Mail,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { getCurrentRecruiter, isAPIError, loginRecruiter } from "@/src/lib/api";

export default function SignInPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getCurrentRecruiter()
      .then(() => router.replace("/"))
      .catch(() => undefined);
  }, [router]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");

    if (!email.trim() || !password) {
      setError("Enter your work email and password to continue.");
      return;
    }

    setIsLoading(true);
    try {
      await loginRecruiter(email, password, rememberMe);
      router.replace("/");
      router.refresh();
    } catch (loginError) {
      setError(
        isAPIError(loginError) && loginError.status === 429
          ? loginError.message
          : "Invalid email or password.",
      );
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="signin-page app-bg relative min-h-screen overflow-hidden text-slate-900">
      <div className="pointer-events-none absolute inset-0" aria-hidden="true">
        <div className="absolute -right-28 -top-36 h-[430px] w-[430px] rounded-full bg-brand/10 blur-3xl" />
        <div className="absolute -bottom-48 left-[42%] h-[420px] w-[420px] rounded-full bg-brand/[0.06] blur-3xl" />
      </div>

      <div className="relative grid min-h-screen lg:grid-cols-[46%_54%]">
        <section className="signin-panel sidebar-bg relative hidden overflow-hidden px-12 py-10 text-white lg:flex lg:flex-col xl:px-16 xl:py-12">
          <div className="absolute inset-0 opacity-30" aria-hidden="true">
            <div className="absolute -left-24 top-32 h-72 w-72 rounded-full border border-white/20" />
            <div className="absolute -left-7 top-52 h-72 w-72 rounded-full border border-white/10" />
            <div className="absolute bottom-12 right-[-80px] h-80 w-80 rotate-12 rounded-[48px] border border-brand/45" />
          </div>

          <BrandMark />

          <div className="relative my-auto max-w-[520px] py-14">
            <div className="mb-7 inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/[0.08] px-4 py-2 text-[12px] font-semibold tracking-wide text-white/90 backdrop-blur">
              <Sparkles className="h-4 w-4 text-[#ff5656]" />
              AI-powered talent intelligence
            </div>
            <h1 className="font-display max-w-[480px] text-[42px] font-bold leading-[1.08] tracking-[-0.045em] xl:text-[50px]">
              Recruitment decisions, <span className="font-accent font-normal italic text-brand-light">elevated.</span>
            </h1>
            <p className="mt-6 max-w-[470px] text-[16px] leading-7 text-white/72">
              A focused workspace for matching exceptional people with the right opportunities—faster, consistently, and with confidence.
            </p>

            <div className="mt-10 grid gap-4 text-[14px] text-white/86 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
              <TrustPoint label="Secure recruiter workspace" />
              <TrustPoint label="Evidence-led candidate review" />
            </div>
          </div>

          <div className="relative flex items-center justify-between border-t border-white/10 pt-6 text-[12px] text-white/55">
            <span>© {new Date().getFullYear()} iSOFT Recruitment</span>
            <span className="inline-flex items-center gap-2"><ShieldCheck className="h-4 w-4" /> Private & confidential</span>
          </div>
        </section>

        <main className="flex min-h-screen items-center justify-center px-5 py-8 sm:px-8 lg:px-12 xl:px-20">
          <div className="signin-card w-full max-w-[470px]">
            <div className="mb-10 lg:hidden">
              <BrandMark dark />
            </div>

            <div className="mb-9">
              <p className="mb-3 text-[11px] font-bold uppercase tracking-[0.16em] text-brand">
                Recruiter portal
              </p>
              <h2 className="font-display text-[34px] font-bold leading-tight tracking-[-0.04em] text-slate-950 sm:text-[38px]">
                Welcome back
              </h2>
              <p className="mt-3 text-[15px] leading-6 text-slate-500">
                Sign in to continue to your recruitment workspace.
              </p>
            </div>

            <form className="space-y-5" noValidate onSubmit={handleSubmit}>
              {error ? (
                <div
                  className="signin-alert rounded-xl border border-brand/20 bg-brand-faint px-4 py-3 text-[13px] leading-5 text-brand-dark"
                  id="sign-in-error"
                  role="alert"
                >
                  {error}
                </div>
              ) : null}

              <div>
                <label className="mb-2 block text-[13px] font-semibold text-slate-700" htmlFor="email">Work email</label>
                <span className="relative block">
                  <Mail className="pointer-events-none absolute left-3.5 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-[#8c8e94]" />
                  <input
                    aria-describedby={error ? "sign-in-error" : undefined}
                    aria-invalid={Boolean(error)}
                    autoComplete="email"
                    autoFocus
                    className="h-[50px] w-full rounded-xl border border-slate-200 bg-white pl-11 pr-4 text-[15px] text-slate-900 outline-none transition placeholder:text-slate-400 hover:border-slate-300 focus:border-brand focus:ring-4 focus:ring-brand/10"
                    id="email"
                    inputMode="email"
                    name="email"
                    onChange={(event) => setEmail(event.target.value)}
                    placeholder="name@company.com"
                    required
                    type="email"
                    value={email}
                  />
                </span>
              </div>

              <div>
                <label className="mb-2 block text-[13px] font-semibold text-slate-700" htmlFor="password">Password</label>
                <span className="relative block">
                  <LockKeyhole className="pointer-events-none absolute left-3.5 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-[#8c8e94]" />
                  <input
                    aria-describedby={error ? "sign-in-error" : undefined}
                    aria-invalid={Boolean(error)}
                    autoComplete="current-password"
                    className="h-[50px] w-full rounded-xl border border-slate-200 bg-white pl-11 pr-12 text-[15px] text-slate-900 outline-none transition placeholder:text-slate-400 hover:border-slate-300 focus:border-brand focus:ring-4 focus:ring-brand/10"
                    id="password"
                    name="password"
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder="Enter your password"
                    required
                    type={showPassword ? "text" : "password"}
                    value={password}
                  />
                  <button
                    aria-label={showPassword ? "Hide password" : "Show password"}
                    aria-pressed={showPassword}
                    className="absolute right-2 top-1/2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-lg text-slate-500 transition hover:bg-brand-faint hover:text-brand-dark focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                    onClick={() => setShowPassword((visible) => !visible)}
                    type="button"
                  >
                    {showPassword ? <EyeOff className="h-[18px] w-[18px]" /> : <Eye className="h-[18px] w-[18px]" />}
                  </button>
                </span>
              </div>

              <div className="flex items-center justify-between gap-4 text-[13px]">
                <label className="flex cursor-pointer items-center gap-2.5 text-[#55575c]" htmlFor="remember-me">
                  <input
                    checked={rememberMe}
                    className="h-4 w-4 rounded border-[#c7c9cd] accent-[#5C0D1B] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#5C0D1B]/30"
                    id="remember-me"
                    onChange={(event) => setRememberMe(event.target.checked)}
                    type="checkbox"
                  />
                  Remember me
                </label>
                <Link
                  className="font-bold text-brand-dark transition hover:text-brand focus-visible:rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30"
                  href="/forgot-password"
                >
                  Forgot password?
                </Link>
              </div>

              <Button
                className="mt-1 h-[50px] w-full text-[15px] shadow-lg shadow-brand/15 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand/20"
                isLoading={isLoading}
                rightIcon={!isLoading ? <ArrowRight className="h-[18px] w-[18px]" /> : undefined}
                type="submit"
              >
                {isLoading ? "Signing in…" : "Sign In"}
              </Button>
            </form>

            <div className="mt-8 border-t border-[#e8e9eb] pt-6 text-center text-[12px] leading-5 text-[#85878c]">
              By continuing, you agree to your organisation&apos;s security and acceptable use policies.
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}

function BrandMark({ dark = false }: { dark?: boolean }) {
  return (
    <Link
      aria-label="iSOFT Recruitment home"
      className={`relative inline-flex items-center gap-3 self-start font-display ${dark ? "text-slate-900" : "text-white"}`}
      href="/sign-in"
    >
      <span className="text-[29px] font-black leading-none tracking-[-0.08em] text-brand">iSOFT</span>
      <span className={`h-6 w-px ${dark ? "bg-brand/20" : "bg-white/25"}`} />
      <span className="text-[17px] font-bold">Recruitment</span>
    </Link>
  );
}

function TrustPoint({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white/10">
        <CheckCircle2 className="h-4 w-4 text-[#ff5656]" />
      </span>
      {label}
    </div>
  );
}
