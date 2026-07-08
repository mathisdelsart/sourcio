import { ImageResponse } from "next/og";

// Social-share card (Open Graph + Twitter). Rendered to a PNG at build time from
// this JSX — no binary asset to maintain — on the brand's navy + periwinkle
// palette. Next automatically wires it into openGraph.images and twitter.images.
export const alt = "Sourcio — cited answers from your own courses";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          height: "100%",
          width: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "80px",
          background: "#15172e",
          color: "#ffffff",
          fontFamily: "sans-serif",
        }}
      >
        {/* Wordmark */}
        <div style={{ display: "flex", alignItems: "center", gap: "22px" }}>
          <div style={{ width: 60, height: 60, borderRadius: 18, background: "#8b8ef0", display: "flex" }} />
          <div style={{ fontSize: 42, fontWeight: 700, letterSpacing: "-0.5px" }}>Sourcio</div>
        </div>

        {/* Headline + supporting line */}
        <div style={{ display: "flex", flexDirection: "column", gap: "26px" }}>
          <div style={{ fontSize: 70, fontWeight: 800, lineHeight: 1.05, maxWidth: 940 }}>
            Answers only from your own courses
          </div>
          <div style={{ fontSize: 34, color: "#c7c9f2", maxWidth: 940, lineHeight: 1.3 }}>
            Every answer cited to its source — or honestly refused when your notes don&apos;t cover it.
          </div>
        </div>

        {/* Footer tag */}
        <div style={{ display: "flex", alignItems: "center", gap: "16px", fontSize: 27, color: "#9aa0c9" }}>
          <div style={{ width: 13, height: 13, borderRadius: 13, background: "#8b8ef0", display: "flex" }} />
          <div>Grounded AI study tutor</div>
        </div>
      </div>
    ),
    { ...size },
  );
}
