// Wires the tool layer to MotherDuck, GitHub and Slack from the environment. Route handlers (Node runtime) call
// toolLayerFromEnv(); tests build a ToolLayer with fakes instead.
import { ToolLayer } from "./executor.ts";
import { allowlistedFetch } from "./http.ts";
import { GithubDispatcher } from "./dispatch.ts";
import { SlackOwnerNotifier } from "./notify.ts";
import { YahooSecResolver } from "./resolver.ts";
import { MotherDuckInboxStore, MotherDuckReadStore, pgQuery } from "./motherduck.ts";
import { type Env, gatewayMode, secretValues, value } from "./env.ts";
import {
  DISPATCH_REF, DISPATCH_WORKFLOW, GITHUB_REPOSITORY, INBOX_DATABASE, MOTHERDUCK_PG_HOST, READ_DATABASE, SEC_USER_AGENT,
  SLACK_CHANNEL_ID,
} from "./constants.ts";

export { ToolLayer } from "./executor.ts";
export { dashboardContext, githubContext, slackContext } from "./identity.ts";
export type * from "./types.ts";

let cached: { env: Env; layer: ToolLayer } | null = null;

export function toolLayerFromEnv(env: Env = process.env): ToolLayer {
  if (cached && cached.env === env) return cached.layer;
  const fetcher = allowlistedFetch();
  const layer = new ToolLayer({
    readStore: new MotherDuckReadStore(pgQuery({ host: MOTHERDUCK_PG_HOST, database: READ_DATABASE,
      token: value(env, "MOTHERDUCK_READ_TOKEN") })),
    inbox: new MotherDuckInboxStore(pgQuery({ host: MOTHERDUCK_PG_HOST, database: INBOX_DATABASE,
      token: value(env, "MOTHERDUCK_INBOX_TOKEN") })),
    dispatcher: new GithubDispatcher({ token: value(env, "GITHUB_DISPATCH_TOKEN"), repository: GITHUB_REPOSITORY,
      workflow: DISPATCH_WORKFLOW, ref: DISPATCH_REF }, fetcher),
    notifier: new SlackOwnerNotifier(value(env, "SLACK_BOT_TOKEN"), SLACK_CHANNEL_ID, fetcher),
    resolver: new YahooSecResolver(allowlistedFetch(fetch, 2500), SEC_USER_AGENT),
    clock: () => new Date(),
    settings: { gatewayMode: gatewayMode(env), secrets: secretValues(env) },
  });
  cached = { env, layer };
  return layer;
}
