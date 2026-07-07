/**
 * Client-side highlighting of the portion of a source excerpt that a grounded
 * answer actually relied on.
 *
 * The backend returns a whole chunk (e.g. an entire CV or slide) with no
 * character offsets, and it never receives the answer/question. But both are
 * available in the browser, so we approximate the relevant span here: we derive
 * salient terms from the answer text and mark their occurrences inside the
 * excerpt. This is a purely visual hint — no network call, no re-ingestion.
 */

/**
 * Short, high-frequency FR + EN words that carry no topical signal. Kept small
 * on purpose: the ≥4-char length filter already removes most noise, this set
 * only trims the few frequent long-ish function words that slip through.
 */
const STOPWORDS = new Set([
  // English
  "this",
  "that",
  "these",
  "those",
  "with",
  "from",
  "have",
  "has",
  "had",
  "will",
  "would",
  "should",
  "could",
  "about",
  "into",
  "than",
  "then",
  "them",
  "they",
  "their",
  "there",
  "here",
  "what",
  "when",
  "where",
  "which",
  "while",
  "your",
  "yours",
  "been",
  "being",
  "were",
  "such",
  "some",
  "also",
  "only",
  "more",
  "most",
  "over",
  "under",
  "each",
  "both",
  "does",
  "done",
  "very",
  "just",
  "like",
  // French
  "dans",
  "pour",
  "avec",
  "sans",
  "sont",
  "cette",
  "cettes",
  "ces",
  "les",
  "des",
  "une",
  "aux",
  "leur",
  "leurs",
  "vous",
  "nous",
  "elle",
  "elles",
  "ils",
  "mais",
  "donc",
  "comme",
  "plus",
  "moins",
  "tout",
  "tous",
  "toute",
  "toutes",
  "entre",
  "selon",
  "ainsi",
  "alors",
  "encore",
  "aussi",
  "peut",
  "peuvent",
  "etre",
  "être",
  "cela",
  "quand",
  "quel",
  "quelle",
  "quels",
  "quelles",
]);

/** Longest term we will ever match; caps pathological highlighting cost. */
const MAX_TERMS = 30;
/** Keep only reasonably specific words. */
const MIN_TERM_LENGTH = 4;

/** Escape regex metacharacters so terms are matched literally. */
export function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Derive de-duplicated highlight terms from free text (typically the answer,
 * optionally prefixed with the question): lowercase, split on non-word runs
 * (the letter range spans Latin-1 accented characters so French words survive),
 * drop short words and stopwords, then cap the count.
 */
export function highlightTerms(text: string | undefined | null): string[] {
  if (!text) return [];
  const seen = new Set<string>();
  const terms: string[] = [];
  // Split on anything that is not an ASCII/accented-Latin letter or a digit.
  // `À-ɏ` covers Latin-1 Supplement + Latin Extended-A/B (é, à, ç…),
  // avoiding `\p{L}` which would need the `u` flag / a higher compile target.
  for (const raw of text.toLowerCase().split(/[^0-9a-zÀ-ɏ]+/)) {
    if (raw.length < MIN_TERM_LENGTH) continue;
    if (STOPWORDS.has(raw)) continue;
    if (seen.has(raw)) continue;
    seen.add(raw);
    terms.push(raw);
    if (terms.length >= MAX_TERMS) break;
  }
  return terms;
}

/** Minimal structural view of a hast node — enough for a text-splitting walk. */
interface HastNode {
  type: string;
  tagName?: string;
  value?: string;
  properties?: { className?: unknown } & Record<string, unknown>;
  children?: HastNode[];
}

/** Container elements whose text must never be highlighted. */
const SKIP_TAGS = new Set(["code", "pre", "script", "style"]);

/** True when this element (or its subtree) must be left untouched. */
function isSkippable(node: HastNode): boolean {
  if (node.tagName && SKIP_TAGS.has(node.tagName)) return true;
  const cls = node.properties?.className;
  const classes = Array.isArray(cls) ? cls : typeof cls === "string" ? [cls] : [];
  // KaTeX math is emitted (before rehype-katex runs) as a span with the "math"
  // class carrying raw LaTeX as text; splitting it would corrupt the formula.
  return classes.some((c) => c === "math" || c === "katex" || String(c).startsWith("math-"));
}

/**
 * A rehype plugin that wraps every case-insensitive occurrence of `terms`
 * inside plain text nodes with `<mark class="source-highlight">`, leaving
 * code, pre and math subtrees alone.
 *
 * It is intended to run BEFORE rehype-katex so math is still an untouched
 * `<span class="math ...">` container at this point and gets skipped, keeping
 * KaTeX rendering intact. Injecting `<mark>` as real hast element nodes (rather
 * than raw HTML in the markdown string) keeps the render safe.
 */
export function rehypeHighlight(terms: string[]) {
  const sorted = [...terms].sort((a, b) => b.length - a.length);
  const pattern = sorted.map(escapeRegExp).filter(Boolean).join("|");

  function splitText(value: string): HastNode[] {
    const re = new RegExp(`(${pattern})`, "gi");
    const parts = value.split(re);
    if (parts.length <= 1) return [{ type: "text", value }];
    const out: HastNode[] = [];
    for (let i = 0; i < parts.length; i++) {
      const piece = parts[i];
      if (piece === "") continue;
      // Odd indices are the captured matches (thanks to the capturing group).
      if (i % 2 === 1) {
        out.push({
          type: "element",
          tagName: "mark",
          properties: { className: ["source-highlight"] },
          children: [{ type: "text", value: piece }],
        });
      } else {
        out.push({ type: "text", value: piece });
      }
    }
    return out;
  }

  function walk(node: HastNode, skip: boolean): void {
    const children = node.children;
    if (!children) return;
    const next: HastNode[] = [];
    for (const child of children) {
      if (!skip && child.type === "text" && typeof child.value === "string") {
        next.push(...splitText(child.value));
        continue;
      }
      if (child.type === "element") {
        walk(child, skip || isSkippable(child));
      }
      next.push(child);
    }
    node.children = next;
  }

  return function plugin() {
    return function transform(tree: unknown): void {
      if (!pattern) return;
      walk(tree as HastNode, false);
    };
  };
}
