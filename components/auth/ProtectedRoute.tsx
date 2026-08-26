import "server-only";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

const cookieName = process.env.AUTH_COOKIE_NAME || "recruitment_session";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  if (!cookies().get(cookieName)) {
    redirect("/sign-in");
  }

  return children;
}
