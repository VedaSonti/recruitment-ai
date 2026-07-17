import type { ReactNode } from "react";
import { cx } from "@/src/lib/utils";

type BadgeTone =
  | "green"
  | "blue"
  | "indigo"
  | "purple"
  | "amber"
  | "red"
  | "grey"
  | "crimson";

export function Badge({
  children,
  className,
  tone = "grey",
}: {
  children: ReactNode;
  className?: string;
  tone?: BadgeTone;
}) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] font-bold leading-none",
        tone === "green" && "bg-[#d9f8e5] text-[#04743b]",
        tone === "blue" && "bg-[#dbeafe] text-[#1d4ed8]",
        tone === "indigo" && "bg-[#e0e7ff] text-[#4338ca]",
        tone === "purple" && "bg-[#f3e8ff] text-[#7e22ce]",
        tone === "amber" && "bg-[#fff4cc] text-[#a65f00]",
        tone === "red" && "bg-[#fee2e2] text-[#b91c1c]",
        tone === "grey" && "bg-[#edf0f4] text-[#667085]",
        tone === "crimson" && "bg-[#e8cfd6] text-crimson-700",
        className,
      )}
    >
      {children}
    </span>
  );
}

export function statusTone(status?: string): BadgeTone {
  switch ((status || "").toLowerCase()) {
    case "open":
    case "interview completed":
    case "sent":
      return "green";
    case "matched":
    case "interview sent":
      return "blue";
    case "approved":
      return "indigo";
    case "shortlisted":
      return "purple";
    case "uplifted":
    case "processing":
    case "duplicate":
      return "amber";
    case "failed":
    case "rejected":
      return "red";
    default:
      return "grey";
  }
}
