import { NextRequest, NextResponse } from "next/server";

const cookieName = process.env.AUTH_COOKIE_NAME || "recruitment_session";
const publicPaths = new Set(["/sign-in", "/forgot-password", "/reset-password"]);

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (publicPaths.has(pathname) || pathname.startsWith("/interview/")) {
    return NextResponse.next();
  }
  if (!request.cookies.get(cookieName)) {
    return NextResponse.redirect(new URL("/sign-in", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
