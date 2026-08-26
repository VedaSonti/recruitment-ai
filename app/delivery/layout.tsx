import { ProtectedRoute } from "@/components/auth/ProtectedRoute";
import type { ReactNode } from "react";

export default function DeliveryLayout({ children }: { children: ReactNode }) {
  return <ProtectedRoute>{children}</ProtectedRoute>;
}
