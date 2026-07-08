import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { ToastProvider } from "@/components/Toast";
import { I18nProvider } from "@/lib/i18n";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

// Public site URL — used as the metadataBase so the Open Graph image resolves to
// an absolute URL. Defaults to the live Vercel URL; override with
// NEXT_PUBLIC_SITE_URL on the host if you later attach a custom domain.
const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://sourcio-tutor.vercel.app";
const DESCRIPTION =
  "An AI study tutor that answers only from your own course materials — every answer cited to its source, or honestly refused when your notes don't cover it.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "Sourcio — cited answers from your own courses",
    template: "%s · Sourcio",
  },
  description: DESCRIPTION,
  applicationName: "Sourcio",
  keywords: ["AI tutor", "cited answers", "study from your courses", "no hallucination", "revision"],
  authors: [{ name: "mathisdelsart" }],
  openGraph: {
    type: "website",
    siteName: "Sourcio",
    title: "Sourcio — cited answers from your own courses",
    description: DESCRIPTION,
    url: SITE_URL,
  },
  twitter: {
    card: "summary_large_image",
    title: "Sourcio — cited answers from your own courses",
    description: DESCRIPTION,
  },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#15172e" },
  ],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="font-sans antialiased">
        <I18nProvider>
          <ToastProvider>{children}</ToastProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
