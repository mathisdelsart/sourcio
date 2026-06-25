import type { KeyboardEvent } from "react";

/**
 * Keyboard handler that fires `action` on Cmd+Enter (macOS) or Ctrl+Enter,
 * the conventional "submit from a multi-line field" shortcut.
 */
export function submitOnCmdEnter(action: () => void) {
  return (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      action();
    }
  };
}
