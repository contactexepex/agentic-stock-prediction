// Wires the tool layer to MotherDuck, GitHub and Slack from the environment. Route handlers (Node runtime) call
// toolLayerFromEnv(); tests build a ToolLayer with fakes instead.
import { ToolLayer } from "./executor.ts";
import { allowlistedFetch } from "./http.ts";
import { GithubDispatcher } from "./dispatch.ts";
import { SlackOwnerNotifier } from "./notify.ts";
import { YahooSecResolver } from "./resolver.ts";
import { DEFAULT_PG_HOST, MotherDuckInboxStore, MotherDuckReadStore, pgQuery } from "./motherduck.ts";
import { type Env, gatewayMode, killSwitch, secretValues, value } from "./env.ts";

export { ToolLayer } from "./executor.ts";
export { dashboardContext, githubContext, slackContext } from "./identity.ts";
export type * from "./types.ts";

let cached: { env: Env; layer: ToolLayer } | null = null;

export function toolLayerFromEnv(env: Env = process.env): ToolLayer {
  if (cached && cached.env === env) return cached.layer;
  const fetcher = allowlistedFetch();
  const host = value(env, "MOTHERDUCK_PG_HOST") ?? DEFAULT_PG_HOST;
  const layer = new ToolLayer({
    readStore: new MotherDuckReadStore(pgQuery({ host, database: value(env, "MOTHERDUCK_READ_DATABASE") ?? "market_brief",
      token: value(env, "MOTHERDUCK_READ_TOKEN") })),
    inbox: new MotherDuckInboxStore(pgQuery({ host, database: value(env, "MOTHERDUCK_INBOX_DATABASE") ?? "market_brief_inbox",
      token: value(env, "MOTHERDUCK_INBOX_TOKEN") })),
    dispatcher: new GithubDispatcher({
      token: value(env, "GITHUB_DISPATCH_TOKEN"),
      repository: value(env, "GITHUB_REPOSITORY") ?? "contactexepex/agentic-stock-prediction",
      workflow: value(env, "GITHUB_DISPATCH_WORKFLOW") ?? "onboard.yml",
      ref: value(env, "GITHUB_DISPATCH_REF") ?? "main",
    }, fetcher),
    notifier: new SlackOwnerNotifier(value(env, "SLACK_BOT_TOKEN"), value(env, "SLACK_OWNER_USER_ID"), fetcher),
    resolver: new YahooSecResolver(allowlistedFetch(fetch, 2500), value(env, "SEC_USER_AGENT")),
    clock: () => new Date(),
    settings: { gatewayMode: gatewayMode(env), killSwitch: killSwitch(env), secrets: secretValues(env) },
  });
  cached = { env, layer };
  return layer;
}
