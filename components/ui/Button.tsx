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
        "inline-flex items-center justify-center gap-2 rounded-[8px] border text-[14px] font-bold transition disabled:cursor-not-allowed disabled:opacity-60",
        size === "sm" && "h-9 px-4",
        size === "md" && "h-11 px-5",
        size === "lg" && "h-13 px-7 text-[15px]",
        variant === "primary" &&
          "border-crimson-700 bg-crimson-700 text-white hover:bg-crimson-800",
        variant === "secondary" &&
          "border-[#d8dee7] bg-white text-[#333438] hover:border-crimson-700 hover:text-crimson-700",
        variant === "ghost" &&
          "border-transparent bg-transparent text-[#333438] hover:bg-[#f3f4f6]",
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
