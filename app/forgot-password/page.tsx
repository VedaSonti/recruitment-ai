"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Mail } from "lucide-react";
import { AuthCard } from "@/components/auth/AuthCard";
import { Button } from "@/components/ui/Button";
import { requestPasswordReset } from "@/src/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setMessage("");
    try {
      const result = await requestPasswordReset(email);
      setMessage(result.message);
    } catch {
      setMessage("If an active account exists, a password reset email has been sent.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthCard eyebrow="Account recovery" title="Reset your password" description="Enter your work email and we’ll send password-reset instructions if an active account exists.">
      {message ? <div className="rounded-[9px] border border-[#c9e6d3] bg-[#eefaf2] px-4 py-3 text-[13px] leading-5 text-[#176b36]" role="status">{message}</div> : null}
      <form className="mt-5 space-y-5" onSubmit={submit}>
        <div>
          <label className="mb-2 block text-[13px] font-bold" htmlFor="recovery-email">Work email</label>
          <span className="relative block">
            <Mail className="pointer-events-none absolute left-3.5 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-[#8c8e94]" />
            <input autoComplete="email" className="h-[50px] w-full rounded-[9px] border border-[#d8dadd] pl-11 pr-4 outline-none transition focus:border-[#5C0D1B] focus:ring-4 focus:ring-[#5C0D1B]/10" id="recovery-email" onChange={(event) => setEmail(event.target.value)} required type="email" value={email} />
          </span>
        </div>
        <Button className="h-[50px] w-full border-[#5C0D1B] bg-[#5C0D1B] hover:bg-[#4b0916]" isLoading={loading} type="submit">Send reset instructions</Button>
      </form>
      <Link className="mt-6 inline-flex items-center gap-2 text-[13px] font-bold text-[#5C0D1B] hover:text-[#E01111]" href="/sign-in"><ArrowLeft className="h-4 w-4" /> Back to Sign In</Link>
    </AuthCard>
  );
}
