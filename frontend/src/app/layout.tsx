import type { Metadata } from "next";
import "./globals.css";
import "./theme.css";
import "leaflet/dist/leaflet.css";
export const metadata: Metadata = { title: "HydroSeismic | Disaster Intelligence", description: "Disaster intelligence and response coordination prototype" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="en"><body>{children}</body></html>; }
