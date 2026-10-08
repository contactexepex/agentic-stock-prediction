// The app's 404 (an unknown market, page or ticker): plain words and a way back.
import Link from "next/link";
import { DEFAULT_MARKET } from "../lib/ui/routes.ts";

export default function NotFound() {
  return (
    <main className="mb-notfound">
      <section className="card">
        <h1>Page not found</h1>
        <p className="muted">There is no page at this address. Markets are India and US; companies are reached from the watchlist.</p>
        <Link className="md-btn filled" href={`/${DEFAULT_MARKET}`}>
          Go to Home
        </Link>
      </section>
    </main>
  );
}
