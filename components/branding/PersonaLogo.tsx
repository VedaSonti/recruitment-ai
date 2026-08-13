import Image from "next/image";
import personaLogo from "@/components/branding/persona-logo.png";
import personaLogoOnDark from "@/components/branding/persona-logo-on-dark.png";
import { cx } from "@/src/lib/utils";

export function PersonaLogo({
  className,
  priority = false,
  tone = "default",
}: {
  className?: string;
  priority?: boolean;
  tone?: "default" | "onDark";
}) {
  return (
    <Image
      alt="Persona - AI-Powered Recruitment"
      className={cx("h-auto object-contain", className)}
      priority={priority}
      src={tone === "onDark" ? personaLogoOnDark : personaLogo}
    />
  );
}
