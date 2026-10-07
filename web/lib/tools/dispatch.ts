// Starts the import: GitHub Actions workflow_dispatch of onboard.yml (session B1 builds the workflow). The token is a
// fine-grained token limited to Actions on this repository. No inputs are sent (an input the workflow does not declare
// makes GitHub answer 422); the workflow (`company.py import-inbox`) imports every inbox.company_commands row that
// its data/ command log has not settled yet.
import type { Dispatcher } from "./types.ts";
import type { FetchLike } from "./http.ts";

export interface DispatchSettings {
  token: string | null;
  repository: string;   // owner/repo
  workflow: string;     // onboard.yml
  ref: string;          // main
}

export class GithubDispatcher implements Dispatcher {
  readonly settings: DispatchSettings;
  readonly fetcher: FetchLike;

  constructor(settings: DispatchSettings, fetcher: FetchLike) {
    this.settings = settings;
    this.fetcher = fetcher;
  }

  async dispatch(): Promise<{ ok: boolean; reason: string | null }> {
    const { token, repository, workflow, ref } = this.settings;
    if (!token) return { ok: false, reason: "dispatch token not configured" };
    if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository) || !/^[A-Za-z0-9_.-]+\.ya?ml$/.test(workflow)) {
      return { ok: false, reason: "dispatch target misconfigured" };
    }
    const url = `https://api.github.com/repos/${repository}/actions/workflows/${workflow}/dispatches`;
    try {
      const response = await this.fetcher(url, {
        method: "POST",
        headers: {
          Accept: "application/vnd.github+json",
          Authorization: `Bearer ${token}`,
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "market-brief-gateway",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref }),
      });
      return response.status === 204 || response.ok ? { ok: true, reason: null } : { ok: false, reason: `GitHub answered ${response.status}` };
    } catch {
      return { ok: false, reason: "GitHub unreachable" };
    }
  }
}
