import { NextResponse, type NextRequest } from "next/server";

const REDIRECTS: Record<string, string> = {
  "/scheduled": "/workspaces",
  "/login": "/",
};

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const redirectTo = REDIRECTS[pathname];
  if (redirectTo) {
    return NextResponse.redirect(new URL(redirectTo, request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
