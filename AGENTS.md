# Project Instructions

## Scope

- Keep the browser application as a single `index.html` file.
- Keep the normalization logic in `index.html` and `parser.js` consistent; the browser does not load `parser.js`.
- Update README when provider setup, credential handling, quota display or deployment behavior changes.
- Preserve unrelated working changes. Publishing documentation does not imply deploying the service.

## Provider Behavior

- Support Codex, MiniMax, Volcengine CodingPlan / AgentPlan, Kimi Code, LongCat, Qianwen AI, Zhipu AI CodingPlan and Google AI.
- Google AI uses the dedicated OAuth account flow, not imported curl auto-detection.
- Preserve the account ID, URL and request body when updating Kimi or MiniMax verification headers.
- Preserve Kimi token rotation and response-cookie handling when changing its refresh flow.
- Distinguish provider business errors from successful HTTP transport; retain the last successful cache on refresh failure.
- Do not infer expired authentication from a 100% quota reading or invent missing quota/reset data.

## Validation

- Run `node --test tests/parser.test.js` after parser changes.
- Run `PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_*.py'` after server changes.
- Run `python3 -m py_compile server.py` and `node --check` on each extracted inline script from `index.html` before pushing.
- For documentation changes, verify claims against the implementation, check local Markdown links and run `git diff --check`; no new tests are required solely for prose.
- Check command exit codes, stderr and expected output. Treat any `fatal:` output as failure even if an outer command exits successfully.
- GitHub requires the `Parser (Node)` and `Server (Python)` checks. Preserve branch protection and wait for both before updating `main`.

## Repository Synchronization

- The Gitea development repository retains its complete history. Publish each requested GitHub synchronization as one reviewed commit based on the current GitHub `main`.
- Inspect remote URLs and fetch the intended remote before publishing; never assume a remote name identifies the correct destination.
- Use a separate publication branch or isolated checkout. Do not reset, rebase or force-push the local development branch or Gitea history to match GitHub's squash history.
- Include pending local changes only within the requested scope; preserve the original working tree and keep recovery references local.
- Review the exact outgoing tree, diff, message and author/committer metadata. Use a GitHub noreply email for public commits and exclude private infrastructure details.
- Push only the intended branch, without unrelated tags or backup refs. If checks are required, create a pull request and wait for them; keep the final main update to one commit.
- Save and print separate local publication and remote SHAs. Both must be non-empty and equal before reporting success; also verify that Gitea's history is unchanged.
- Confirm the final commit count and pull-request state, then remove temporary remote publication branches.

## Deployment

- Deploy through the Portainer Stack named `coding-plan-quota-dashboard` when deployment is requested.
- Keep persistent runtime data under `/docker/coding_plan_quota_dashboard/data/`.
- Verify `http://<DEPLOY_HOST>:8080/` returns HTTP 200 after deployment; substitute the actual host privately, never commit it.
- Verify the affected UI or provider flow as well; HTTP 200 alone does not prove the feature works.
- Quote remote SSH command strings to prevent local expansion of remote variables or command substitutions; prefer a remote script for complex commands.
- For remote background jobs, check process state for zombies as well as completion logs and artifacts; `kill -0` alone is insufficient.

## Security

- Keep credentials and personal information out of source code, tests, README, logs and commits. Use synthetic or clearly redacted fixtures, never real curl requests containing tokens, cookies, device IDs or proxy credentials.
- Execute imported curl requests without a shell. Preserve the endpoint allowlist unless the user explicitly approves an additional provider.
- Treat the entire runtime data directory and its backups as sensitive. `requests.json` can contain raw curl, account AK/SK and refresh tokens; `credentials.json` may contain legacy credentials; cached responses may contain account information.
- Preserve removal of separate Kimi refresh fields and proxy settings, and masking of secret fields in API responses. Saved curl text remains sensitive; do not describe `/api/requests` as fully sanitized.
- The UI lock is an editing convenience, not authentication. Do not expose the service beyond a trusted network without access controls.
