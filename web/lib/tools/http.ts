// Outbound HTTPS from the web tier goes only to these hosts (docs/SPEC.md section 9: HTTPS allowlist, free sources).
export const ALLOWED_HOSTS = new Set([
  "slack.com",                 // Web API: views.open/update, chat.postMessage
  "hooks.slack.com",           // response_url of commands and interactions
  "api.github.com",            // workflow_dispatch; /user after GitHub sign-in
  "github.com",                // OAuth code exchange
  "query1.finance.yahoo.com",  // symbol search for the add summary
  "query2.finance.yahoo.com",
  "www.sec.gov",               // ticker -> CIK map for the add summary
  "api.anthropic.com",         // Claude API: the assistant's explain tool (B8)
]);

export type FetchLike = (url: string, init?: RequestInit) => Promise<Response>;

/** fetch limited to ALLOWED_HOSTS over HTTPS, with a timeout. */
export function allowlistedFetch(base: FetchLike = fetch, timeoutMs = 4000): FetchLike {
  return async (url, init = {}) => {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:" || !ALLOWED_HOSTS.has(parsed.hostname) || parsed.username || parsed.password) {
      throw new Error(`host not on the allowlist: ${parsed.hostname}`);
    }
    return base(url, { ...init, redirect: "error", signal: init.signal ?? AbortSignal.timeout(timeoutMs) });
  };
}
