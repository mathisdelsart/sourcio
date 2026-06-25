"use client";

import { Button } from "@/components/Button";
import { useToast } from "@/components/Toast";
import { answerFilename, buildAnswerMarkdown, type ExportAnswerInput } from "@/lib/exportAnswer";

/** Inline copy icon. */
function CopyIcon() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h10" />
    </svg>
  );
}

/** Inline download icon. */
function DownloadIcon() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      className="h-4 w-4"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 3v12" />
      <path d="m7 10 5 5 5-5" />
      <path d="M5 20h14" />
    </svg>
  );
}

/**
 * A compact action area to export a single grounded answer with its citations,
 * either to the clipboard or as a downloadable `.md` file. Frontend-only: the
 * Markdown is built from data already present in the UI.
 */
export function ExportActions({ question, answer, sources }: ExportAnswerInput) {
  const toast = useToast();
  const payload: ExportAnswerInput = { question, answer, sources };

  async function copyMarkdown() {
    const markdown = buildAnswerMarkdown(payload);
    try {
      await navigator.clipboard.writeText(markdown);
      toast.push("Copied to clipboard.", "success");
    } catch {
      toast.push("Could not copy to clipboard.", "error");
    }
  }

  function downloadMarkdown() {
    const markdown = buildAnswerMarkdown(payload);
    try {
      const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = answerFilename(question);
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      toast.push("Download started.", "success");
    } catch {
      toast.push("Could not prepare the download.", "error");
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        variant="ghost"
        onClick={copyMarkdown}
        aria-label="Copy answer and citations as Markdown"
      >
        <CopyIcon />
        Copy as Markdown
      </Button>
      <Button
        variant="ghost"
        onClick={downloadMarkdown}
        aria-label="Download answer and citations as a Markdown file"
      >
        <DownloadIcon />
        Download .md
      </Button>
    </div>
  );
}
