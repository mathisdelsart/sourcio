import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";

/**
 * Render markdown with GitHub-flavoured tables/lists and KaTeX math.
 *
 * Math is written as `$...$` (inline) / `$$...$$` (block) by the backend.
 * Raw HTML is NOT enabled (no `rehype-raw`), so untrusted markdown cannot
 * inject arbitrary HTML — only the standard markdown surface is rendered.
 */
export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose-tutor">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
