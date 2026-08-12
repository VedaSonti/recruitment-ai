"use client";

import type { ButtonHTMLAttributes, ReactNode } from "react";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { cx } from "@/src/lib/utils";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md" | "lg";

export function Button({
  children,
  className,
  disabled,
  isLoading,
  leftIcon,
  rightIcon,
  size = "md",
  variant = "primary",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  isLoading?: boolean;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
  size?: ButtonSize;
  variant?: ButtonVariant;
}) {
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-xl border text-[14px] font-semibold shadow-sm transition duration-200 focus-visible:ring-2 focus-visible:ring-brand/20 disabled:cursor-not-allowed disabled:opacity-60",
        size === "sm" && "h-9 px-4",
        size === "md" && "h-11 px-5",
        size === "lg" && "h-13 px-7 text-[15px]",
        variant === "primary" &&
          "border-brand bg-brand text-white shadow-brand/10 hover:-translate-y-0.5 hover:border-brand-dark hover:bg-brand-dark hover:shadow-md",
        variant === "secondary" &&
          "border-slate-200 bg-white text-slate-700 hover:-translate-y-0.5 hover:border-brand/40 hover:text-brand-dark hover:shadow-md",
        variant === "ghost" &&
          "border-transparent bg-transparent text-slate-700 shadow-none hover:bg-slate-100",
        variant === "danger" &&
          "border-[#dc2626] bg-[#dc2626] text-white hover:bg-[#b91c1c]",
        className,
      )}
      disabled={disabled || isLoading}
      {...props}
    >
      {isLoading ? <LoadingSpinner size="sm" /> : leftIcon}
      {children}
      {rightIcon}
    </button>
  );
}
