"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, LockKeyhole } from "lucide-react";
import { AuthCard } from "@/components/auth/AuthCard";
import { Button } from "@/components/ui/Button";
import { resetRecruiterPassword } from "@/src/lib/api";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    setToken(new URLSearchParams(window.location.search).get("token") || "");
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (!token) {
      setError("This password reset link is invalid or incomplete.");
      return;
    }
    if (password !== confirmation) {
      setError("Passwords do not match.");
      return;
    }
    setLoading(true);
    try {
      const result = await resetRecruiterPassword(token, password);
      setSuccess(result.message);
      window.setTimeout(() => router.replace("/sign-in"), 1400);
    } catch (resetError) {
      setError(resetError instanceof Error ? resetError.message : "Password reset failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthCard eyebrow="Secure account recovery" title="Choose a new password" description="Use a strong password you haven’t used for this account before.">
      {error ? <div className="rounded-[9px] border border-[#e9b9c0] bg-[#F2E1E3] px-4 py-3 text-[13px] text-[#5C0D1B]" role="alert">{error}</div> : null}
      {success ? <div className="rounded-[9px] border border-[#c9e6d3] bg-[#eefaf2] px-4 py-3 text-[13px] text-[#176b36]" role="status">{success}</div> : null}
      <form className="mt-5 space-y-5" onSubmit={submit}>
        <PasswordField id="new-password" label="New password" onChange={setPassword} show={showPassword} toggle={() => setShowPassword((value) => !value)} value={password} />
        <PasswordField id="confirm-password" label="Confirm password" onChange={setConfirmation} show={showPassword} value={confirmation} />
        <p className="text-[12px] leading-5 text-[#77797f]">At least 12 characters with uppercase, lowercase, and a number.</p>
        <Button className="h-[50px] w-full border-[#5C0D1B] bg-[#5C0D1B] hover:bg-[#4b0916]" disabled={Boolean(success)} isLoading={loading} type="submit">Reset password</Button>
      </form>
      <Link className="mt-6 inline-block text-[13px] font-bold text-[#5C0D1B] hover:text-[#E01111]" href="/sign-in">Return to Sign In</Link>
    </AuthCard>
  );
}

function PasswordField({ id, label, onChange, show, toggle, value }: { id: string; label: string; onChange: (value: string) => void; show: boolean; toggle?: () => void; value: string }) {
  return <div><label className="mb-2 block text-[13px] font-bold" htmlFor={id}>{label}</label><span className="relative block"><LockKeyhole className="pointer-events-none absolute left-3.5 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-[#8c8e94]" /><input autoComplete="new-password" className="h-[50px] w-full rounded-[9px] border border-[#d8dadd] pl-11 pr-12 outline-none transition focus:border-[#5C0D1B] focus:ring-4 focus:ring-[#5C0D1B]/10" id={id} minLength={12} onChange={(event) => onChange(event.target.value)} required type={show ? "text" : "password"} value={value} />{toggle ? <button aria-label={show ? "Hide password" : "Show password"} className="absolute right-2 top-1/2 flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded text-[#77797f] hover:bg-[#F2E1E3]" onClick={toggle} type="button">{show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}</button> : null}</span></div>;
}
