/**
 * Pure helpers for exporting a grounded answer as clean, reusable Markdown.
 *
 * The shape is intentionally small: a question, the answer body, and the
 * pre-formatted citation labels already produced by the backend. Keeping this
 * free of DOM/clipboard concerns makes it trivial to reason about and reuse.
 */

export interface ExportAnswerInput {
  question: string;
  answer: string;
  sources: string[];
}

/**
 * Build a Markdown document for a single answer and its citations.
 *
 * Format:
 *
 *   **Q:** <question>
 *
 *   <answer>
 *
 *   **Sources**
 *   - <label 1>
 *   - <label 2>
 *
 * The "Sources" block is omitted entirely when there are no citation labels.
 */
export function buildAnswerMarkdown({ question, answer, sources }: ExportAnswerInput): string {
  const blocks: string[] = [`**Q:** ${question.trim()}`, answer.trim()];

  const labels = sources.map((s) => s.trim()).filter((s) => s.length > 0);
  if (labels.length > 0) {
    const list = labels.map((label) => `- ${label}`).join("\n");
    blocks.push(`**Sources**\n${list}`);
  }

  return `${blocks.join("\n\n")}\n`;
}

/** A safe, lowercase, hyphenated filename stem derived from the question. */
export function answerFilename(question: string): string {
  const stem = question
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 50)
    .replace(/-+$/g, "");
  return stem ? `answer-${stem}.md` : "answer.md";
}
