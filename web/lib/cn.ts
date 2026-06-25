/** Join class names, dropping falsy values. A tiny `clsx` substitute. */
export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
