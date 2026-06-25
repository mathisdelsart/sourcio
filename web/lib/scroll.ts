/**
 * Smoothly scroll to the element with the given id, honouring the user's
 * reduced-motion preference (falls back to an instant jump). Also moves focus
 * to the target for keyboard and screen-reader users.
 */
export function scrollToId(id: string): void {
  if (typeof document === "undefined") return;
  const el = document.getElementById(id);
  if (!el) return;

  const prefersReduced =
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  el.scrollIntoView({
    behavior: prefersReduced ? "auto" : "smooth",
    block: "start",
  });

  // Make the section programmatically focusable without a permanent tab stop.
  const previousTabIndex = el.getAttribute("tabindex");
  if (previousTabIndex === null) el.setAttribute("tabindex", "-1");
  (el as HTMLElement).focus({ preventScroll: true });
  if (previousTabIndex === null) {
    el.addEventListener(
      "blur",
      () => el.removeAttribute("tabindex"),
      { once: true },
    );
  }
}
