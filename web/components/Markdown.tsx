import type { ComponentProps } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { rehypeHighlight } from "@/lib/highlight";

/**
 * LaTeX environments that are valid math on their own and are frequently
 * emitted by the backend / transcribed from slides WITHOUT `$$` fences.
 * The trailing `*` (starred variants) is handled separately in the regex.
 */
const MATH_ENVIRONMENTS = [
  "cases",
  "aligned",
  "align",
  "alignat",
  "matrix",
  "bmatrix",
  "pmatrix",
  "vmatrix",
  "Vmatrix",
  "Bmatrix",
  "smallmatrix",
  "array",
  "equation",
  "gather",
  "gathered",
  "split",
  "multline",
  "eqnarray",
].join("|");

const BRACKET_DISPLAY_RE = /\\\[([\s\S]*?)\\\]/g;
const BRACKET_INLINE_RE = /\\\(([\s\S]*?)\\\)/g;
const BARE_ENV_RE = new RegExp(
  `\\\\begin\\{(${MATH_ENVIRONMENTS})(\\*?)\\}[\\s\\S]*?\\\\end\\{\\1\\2\\}`,
  "g",
);

/**
 * Regions whose contents must NOT be touched by the math normalizer:
 * fenced code blocks, inline code, and already-delimited math spans.
 * The capturing group makes `String.prototype.split` keep these regions,
 * so we can transform only the plain segments between them.
 *
 * The single-`$` alternative requires at least one inner character
 * (`[^$\n]+`, not `*`): otherwise a bare, unpaired `$$` (e.g. a restated
 * formula missing its opening `$$`) matches here as an "empty" inline span
 * and is protected verbatim, skipping `escapeStrayDoubleDollar` below and
 * leaking as an unterminated KaTeX delimiter.
 */
const PROTECTED_RE =
  /(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`|\$\$[\s\S]*?\$\$|\$[^$\n]+\$)/g;

/**
 * Wrap common bare LaTeX (not already inside `$`/`$$`) in math delimiters so
 * that remark-math picks it up and KaTeX renders it, instead of leaking raw
 * LaTeX into the page:
 *   - `\[ ... \]`  -> `$$ ... $$`  (display math)
 *   - `\( ... \)`  -> `$ ... $`    (inline math)
 *   - standalone `\begin{env}...\end{env}` -> `$$ ... $$`
 */
/**
 * Guard against a stray, unpaired `$$` (e.g. the model restates a formula in
 * prose and appends a closing `$$` for it but forgets the opening one) opening
 * a display-math span that never closes and swallowing the rest of the answer
 * as raw text. Balanced `$$...$$` spans are already split out as PROTECTED
 * regions before this runs, so any `$$` reaching here is unpaired within its
 * segment: if the count of `$$` tokens is odd, escape the last one so it
 * renders literally instead of opening an unterminated KaTeX block.
 */
function escapeStrayDoubleDollar(segment: string): string {
  const matches = Array.from(segment.matchAll(/\$\$/g));
  if (matches.length % 2 === 0) return segment;
  const at = matches[matches.length - 1].index;
  return `${segment.slice(0, at)}\\$\\$${segment.slice(at + 2)}`;
}

/**
 * Guard against a single stray `$` in plain text (e.g. a price, or an unclosed
 * inline-math delimiter) opening a math span that never closes. Balanced
 * `$...$` / `$$...$$` spans are already split out as PROTECTED regions before
 * this runs, so any `$` reaching here is unpaired within its segment: if the
 * count of unescaped `$` is odd, escape the last one so it renders literally.
 * Run on the RAW segment, before the bracket rewrites insert their own `$`.
 */
function escapeStrayDollar(segment: string): string {
  const positions: number[] = [];
  for (let i = 0; i < segment.length; i++) {
    if (segment[i] === "$" && (i === 0 || segment[i - 1] !== "\\")) {
      positions.push(i);
    }
  }
  if (positions.length % 2 === 0) return segment;
  const last = positions[positions.length - 1];
  return `${segment.slice(0, last)}\\$${segment.slice(last + 1)}`;
}

function normalizePlainSegment(segment: string): string {
  return escapeStrayDollar(escapeStrayDoubleDollar(segment))
    .replace(BRACKET_DISPLAY_RE, (_match, inner: string) => `$$${inner}$$`)
    .replace(BRACKET_INLINE_RE, (_match, inner: string) => `$${inner}$`)
    .replace(BARE_ENV_RE, (match: string) => `$$\n${match}\n$$`);
}

/**
 * Normalize a markdown string before rendering. Code fences, inline code and
 * existing `$`/`$$` math spans are preserved verbatim; only the plain text
 * between them is rewritten, which avoids double-wrapping and keeps code
 * samples intact.
 */
export function normalizeMath(markdown: string): string {
  if (!markdown) return markdown;
  const parts = markdown.split(PROTECTED_RE);
  return parts
    .map((part, index) =>
      // Odd indices are the captured protected regions -> leave untouched.
      index % 2 === 1 ? part : normalizePlainSegment(part),
    )
    .join("");
}

/**
 * Render markdown with GitHub-flavoured tables/lists and KaTeX math.
 *
 * Math is normally written as `$...$` (inline) / `$$...$$` (block) by the
 * backend, but slide transcriptions sometimes emit bare LaTeX (`\[..\]`,
 * `\(..\)`, `\begin{cases}..\end{cases}`); `normalizeMath` wraps those so they
 * still render. rehype-katex is configured to fail soft (`throwOnError:false`,
 * `strict:false`) so slightly-off expressions render as best-effort instead of
 * aborting.
 *
 * Raw HTML is NOT enabled (no `rehype-raw`), so untrusted markdown cannot
 * inject arbitrary HTML — only the standard markdown surface is rendered.
 *
 * When `highlight` terms are provided, a small rehype plugin wraps their
 * occurrences in `<mark>` on the rendered text nodes. It runs BEFORE
 * rehype-katex so math is still an untouched `<span class="math">` container
 * and gets skipped, leaving KaTeX rendering intact.
 */
export function Markdown({
  children,
  highlight,
}: {
  children: string;
  highlight?: string[];
}) {
  const rehypePlugins: ComponentProps<typeof ReactMarkdown>["rehypePlugins"] = [
    ...(highlight && highlight.length > 0 ? [rehypeHighlight(highlight)] : []),
    // `errorColor: currentColor` renders a malformed expression in the normal
    // text color instead of KaTeX's alarming red, keeping fail-soft unobtrusive.
    [rehypeKatex, { throwOnError: false, strict: false, errorColor: "currentColor" }],
  ];
  return (
    <div className="prose-tutor">
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={rehypePlugins}>
        {normalizeMath(children)}
      </ReactMarkdown>
    </div>
  );
}
