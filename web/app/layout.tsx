import type { Metadata } from "next";
import { Barlow, Barlow_Condensed } from "next/font/google";
import Link from "next/link";
import "./globals.css";
import { Providers } from "./providers";
import { ModeBadge } from "@/components/ModeBadge";

const barlow = Barlow({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-barlow" });
const barlowCondensed = Barlow_Condensed({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-barlow-condensed",
});

export const metadata: Metadata = {
  title: "GoodPart",
  description: "Visual inspection that learns from good parts only, with known error rates.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${barlow.variable} ${barlowCondensed.variable}`}>
      <body className="min-h-screen antialiased">
        <Providers>
          <header className="border-b border-rule bg-housing">
            <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-8 gap-y-2 px-4 py-3 sm:px-6">
              <Link href="/" className="font-display text-2xl font-bold tracking-tight">
                Good<span className="text-pass">Part</span>
              </Link>
              <nav className="flex flex-wrap gap-5 text-[15px] text-ink-dim">
                <Link className="hover:text-ink" href="/">Stations</Link>
                <Link className="hover:text-ink" href="/setup">New station</Link>
                <Link className="hover:text-ink" href="/evaluation">Evaluation</Link>
              </nav>
              <div className="ml-auto">
                <ModeBadge />
              </div>
            </div>
          </header>
          <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
