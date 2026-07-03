import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";

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
 */
const PROTECTED_RE =
  /(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`|\$\$[\s\S]*?\$\$|\$[^$\n]*\$)/g;

/**
 * Wrap common bare LaTeX (not already inside `$`/`$$`) in math delimiters so
 * that remark-math picks it up and KaTeX renders it, instead of leaking raw
 * LaTeX into the page:
 *   - `\[ ... \]`  -> `$$ ... $$`  (display math)
 *   - `\( ... \)`  -> `$ ... $`    (inline math)
 *   - standalone `\begin{env}...\end{env}` -> `$$ ... $$`
 */
function normalizePlainSegment(segment: string): string {
  return segment
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
 */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose-tutor">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false }]]}
      >
        {normalizeMath(children)}
      </ReactMarkdown>
    </div>
  );
}
