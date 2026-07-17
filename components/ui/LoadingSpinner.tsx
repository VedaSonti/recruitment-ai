import { cx } from "@/src/lib/utils";

export function LoadingSpinner({
  className,
  size = "md",
}: {
  className?: string;
  size?: "sm" | "md" | "lg";
}) {
  return (
    <span
      className={cx(
        "inline-block animate-spin rounded-full border-2 border-current border-r-transparent",
        size === "sm" && "h-4 w-4",
        size === "md" && "h-6 w-6",
        size === "lg" && "h-9 w-9",
        className,
      )}
    />
  );
}
