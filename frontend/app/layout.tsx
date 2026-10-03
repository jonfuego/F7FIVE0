import type { Metadata, Viewport } from "next";
import "./globals.css";
import CastBootstrap from "@/components/CastBootstrap";
import { MiniPlayer } from "@/components/MiniPlayer";
import ServiceWorkerRegistrar from "@/components/ServiceWorkerRegistrar";
import { QueueProvider } from "@/lib/queue";

export const metadata: Metadata = {
  title: {
    default: "F7FIVE0",
    template: "%s · F7FIVE0",
  },
  description: "Personal media streaming for family and close friends.",
  applicationName: "F7FIVE0",
  manifest: "/manifest.json",
  formatDetection: {
    telephone: false,
  },
  openGraph: {
    title: "F7FIVE0",
    description: "Personal media streaming for family and close friends.",
    siteName: "F7FIVE0",
    type: "website",
  },
  robots: {
    index: false,
    follow: false,
  },
};

export const viewport: Viewport = {
  themeColor: "#000000",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

const FONTS_HREF =
  "https://fonts.googleapis.com/css2?" +
  [
    "family=Archivo:wght@400;500;600;700;800;900",
  ].join("&") +
  "&display=swap";

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link href={FONTS_HREF} rel="stylesheet" />
        <link rel="manifest" href="/manifest.json" />
        <link rel="apple-touch-icon" href="/icons/apple-touch-icon-180.png" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <meta name="apple-mobile-web-app-title" content="F7FIVE0" />
      </head>
      <body>
        <CastBootstrap />
        <ServiceWorkerRegistrar />
        <QueueProvider>
          {children}
          <MiniPlayer />
        </QueueProvider>
      </body>
    </html>
  );
}
