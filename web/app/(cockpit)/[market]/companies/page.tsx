// Page 10, Companies (design/mockups/10-companies/; B14): the server part keeps the metadata, the client part reads
// the endpoint and sends the requests through B11's preview and commands routes.
import type { Metadata } from "next";
import type { Market } from "../../../../lib/data/constants.ts";
import { CompaniesPage } from "./_parts/companies-page.tsx";

export const metadata: Metadata = { title: "Companies" };

export default async function Page({ params }: { params: Promise<{ market: string }> }) {
  return <CompaniesPage market={(await params).market as Market} />;
}
