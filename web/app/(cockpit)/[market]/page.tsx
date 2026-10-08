// Page 01, Home (design/mockups/01-home/; B14): the server part keeps the metadata, the client part (in `_home/`, a
// private folder beside the other pages' route folders) reads the endpoint.
import type { Metadata } from "next";
import type { Market } from "../../../lib/data/constants.ts";
import { HomePage } from "./_home/home-page.tsx";

export const metadata: Metadata = { title: "Home" };

export default async function Page({ params }: { params: Promise<{ market: string }> }) {
  return <HomePage market={(await params).market as Market} />;
}
