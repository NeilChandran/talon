import type { AppRouterInstance } from "next/dist/shared/lib/app-router-context.shared-runtime";
import type { MouseEvent } from "react";

/** Full page navigation — bypasses broken Next.js client router. */
export function hardNavigateClick(href: string) {
  return (e: MouseEvent) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
    e.preventDefault();
    window.location.assign(href);
  };
}

/** Next.js client nav with hard fallback when hydration/router is stuck. */
export function navigateClick(
  router: AppRouterInstance,
  href: string,
  pathname?: string
) {
  return (e: MouseEvent) => {
    e.preventDefault();
    if (pathname) {
      const already =
        href === "/"
          ? pathname === "/"
          : pathname === href || pathname.startsWith(`${href}/`);
      if (already) return;
    }
    router.push(href);
    window.setTimeout(() => {
      const current = window.location.pathname;
      const arrived =
        href === "/"
          ? current === "/"
          : current === href || current.startsWith(`${href}/`);
      if (!arrived) window.location.assign(href);
    }, 200);
  };
}

export function navigateTo(router: AppRouterInstance, href: string) {
  router.push(href);
  window.setTimeout(() => {
    const current = window.location.pathname;
    const arrived =
      href === "/"
        ? current === "/"
        : current === href || current.startsWith(`${href}/`);
    if (!arrived) window.location.assign(href);
  }, 200);
}
