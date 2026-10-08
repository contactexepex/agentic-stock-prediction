// The component gallery (B7): the shared components with labelled sample values, for the page sessions and the UI
// harness. Not a page of SPEC section 6 and not in the navigation.
import type { Metadata } from "next";
import type { Market } from "../../../../lib/data/constants.ts";
import { Gallery } from "./_parts/gallery.tsx";

export const metadata: Metadata = { title: "Component gallery" };

export default async function Page({ params }: { params: Promise<{ market: string }> }) {
  return <Gallery market={(await params).market as Market} />;
}
