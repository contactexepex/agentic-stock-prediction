// Page 08, Track record (design/mockups/08-track-record/), owned by B16: the server component sets the title and
// renders the client page, which reads GET /api/v1/markets/{market}/track-record.
import type { Metadata } from "next";
import type { Market } from "../../../../lib/data/constants.ts";
import { TrackRecordPage } from "./_parts/track-record-page.tsx";

export const metadata: Metadata = { title: "Track record" };

export default async function Page({ params }: { params: Promise<{ market: string }> }) {
  return <TrackRecordPage market={(await params).market as Market} />;
}
