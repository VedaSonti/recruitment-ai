import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import type { ReactNode } from "react";

export default function UpliftLayout({ children }: { children: ReactNode }) {
  return <ProtectedRoute>{children}</ProtectedRoute>;
}
