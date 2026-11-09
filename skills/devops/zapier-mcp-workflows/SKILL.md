---
name: zapier-mcp-workflows
description: "Use when connecting Zapier MCP presets to Hermes for inbound GitHub issue/PR events, Linear issues on the kanban board, or Airtable record sync."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [Zapier, MCP, GitHub, Linear, Airtable, Webhooks, Kanban]
    related_skills: [webhook-subscriptions, linear, airtable, github-auth, kanban-worker, github-code-review, native-mcp]
---

# Zapier MCP Workflows

Three Hermes workflows that use Zapier MCP presets. Each preset is added with `hermes mcp add --preset` and OAuth. No API keys, bearer tokens, or webhook secrets belong in this file, in git, or on the command line.

Preset `zapier-github` connects to `https://mcp.zapier.com/api/v1/connect` with OAuth. Presets `zapier-linear` and `zapier-airtable` use the same command shape and OAuth. If `hermes mcp add` reports `Unknown MCP preset`, that preset is not in this install yet. Stop and tell the user. Do not substitute a pasted token.

`hermes mcp add` is interactive: it starts OAuth and a live connection probe. Run it only when the user has asked to connect that Zapier account. Do not enable extra Zapier actions, do not create webhook subscriptions against a gateway the user did not name, and do not send email.

## When to Use

- GitHub issue and pull request events should wake a Hermes agent through `hermes webhook subscribe`.
- A Linear issue in triage (or a new unstarted issue) should become a Hermes kanban card, and the resulting PR or commit link should go back on the Linear issue.
- An Airtable base has rows that need action, and a cron job or a manual run should update those records and write a status field.

Leave these alone:

- Day-to-day GitHub repo commands. Use `gh` (`github-auth`) and the native GitHub MCP example in `native-mcp`.
- Linear and Airtable calls the user wants as plain curl. The `linear` and `airtable` skills stay the default.
- Lovable projects. See the section at the bottom. This repository is not a Lovable app.

## Connect a preset

```bash
hermes mcp add zapier-github --preset zapier-github --auth oauth
hermes mcp add zapier-linear --preset zapier-linear --auth oauth
hermes mcp add zapier-airtable --preset zapier-airtable --auth oauth
```

Add only the preset the workflow needs. Then confirm what connected:

```bash
hermes mcp list
hermes mcp test zapier-github
```

Discovered tools are named `mcp_<server>_<tool>` (hyphens become underscores), the same convention as `native-mcp`. Call a tool only after `hermes mcp test <name>` lists it. Enable read and update actions the workflow names below. Leave email, deletes, and schema edits disabled.

## 1. GitHub inbound events

Preset: `zapier-github`. Endpoint: `https://mcp.zapier.com/api/v1/connect`. Auth: OAuth.

Use this preset only to deliver inbound GitHub `issues` and `pull_request` events into `hermes webhook subscribe`. Day-to-day repo commands stay on `gh` and the native GitHub MCP server documented in `skills/mcp/native-mcp` (`npx -y @modelcontextprotocol/server-github`, added with `hermes mcp add github --command npx --args -y @modelcontextprotocol/server-github`). Authenticate `gh` with `github-auth`. Review the diff with `github-code-review`.

### Subscribe

Enable the webhook platform first if `hermes webhook list` says it is off. Setup is in `webhook-subscriptions` (gateway setup, port, HMAC secret). Then create the two subscriptions already documented there. Replace the example chat id with the user's chat before running the issues command.

Issues, delivered to the user's chat:

```bash
hermes webhook subscribe github-issues \
  --events "issues" \
  --prompt "New GitHub issue #{issue.number}: {issue.title}\n\nAction: {action}\nAuthor: {issue.user.login}\nBody:\n{issue.body}\n\nPlease triage this issue." \
  --deliver telegram \
  --deliver-chat-id "-100123456789"
```

Pull requests, delivered as a GitHub comment, with the code-review skill loaded:

```bash
hermes webhook subscribe github-prs \
  --events "pull_request" \
  --prompt "PR #{pull_request.number} {action}: {pull_request.title}\nBy: {pull_request.user.login}\nBranch: {pull_request.head.ref}\n\n{pull_request.body}" \
  --skills "github-code-review" \
  --deliver github_comment
```

To deliver that same PR run to the user's chat, keep the command and replace `--deliver github_comment` with `--deliver telegram` and `--deliver-chat-id` set to the user's chat (the same flags as the issues subscription).

`hermes webhook subscribe` prints a webhook URL and an HMAC secret. The secret stays on that machine (`hermes webhook list`). Do not commit it.

If GitHub can reach the gateway, point the repo webhook at the printed URL the way `webhook-subscriptions` describes: content type `application/json`, secret from the subscription, events Issues or Pull requests. Skip Zapier in that case.

### When the gateway is not public

When the gateway is not public, Zapier can POST GitHub events to the Hermes webhook URL.

1. Add the preset: `hermes mcp add zapier-github --preset zapier-github --auth oauth`.
2. In the user's Zapier account, forward GitHub issue and pull request events to the URL `hermes webhook subscribe` printed. POST the original GitHub JSON body so `{issue.*}` and `{pull_request.*}` still resolve.
3. Set header `X-GitHub-Event` to `issues` or `pull_request`. The `--events` filter ignores any other value (a missing header is treated as `unknown`).
4. Sign the raw body with the subscription secret. Hermes accepts `X-Hub-Signature-256: sha256=<hex hmac-sha256>` or `X-Webhook-Signature: <hex hmac-sha256>`. A route with a secret and no recognized signature header is rejected.
5. Check the route with `hermes webhook test github-issues` or `hermes webhook test github-prs` and a sample payload. That local test does not create a Zapier action.

Do not turn on Zapier email, chat, or GitHub write actions for this preset.

## 2. Linear issue to Hermes kanban

Preset: `zapier-linear`.

```bash
hermes mcp add zapier-linear --preset zapier-linear --auth oauth
```

The `linear` skill is curl plus `LINEAR_API_KEY` and has no MCP server. Use that curl path unless the user has connected this preset. `LINEAR_API_KEY` comes from the environment (`hermes setup` or `~/.hermes/.env`). Do not print the key.

### Read new and triage issues

Curl, same request shape as the linear skill's state-type filter. Triage:

```bash
curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ issues(filter: { state: { type: { in: [\"triage\"] } } }, first: 20) { nodes { id identifier title url description priority state { name type } } } }"}' | python3 -m json.tool
```

New issues that are already planned use state type `unstarted`. Swap `triage` for `unstarted` in that query, or follow the linear skill's "Filter issues by state type" example.

Zapier MCP alternative: after `hermes mcp test zapier-linear`, call the listed Linear search or list action that returns issues in triage. Read only. Do not create or delete Linear issues from this step.

### Open a kanban card

One card per Linear identifier. `--idempotency-key` returns the existing card when this issue was already imported (`hermes_cli/kanban.py`). `kanban-worker` is loaded automatically for dispatched workers; pass extra skills with `--skill`.

Triage issues park for a specifier (`--triage`). Issues ready to implement use a git worktree so the worker can commit:

```bash
hermes kanban init
hermes kanban create "ENG-123: <title>" \
  --body "Linear: <issue url>
Identifier: ENG-123
State: triage

<description>" \
  --assignee <profile> \
  --workspace worktree \
  --triage \
  --idempotency-key "linear:ENG-123" \
  --skill linear \
  --skill github-pr-workflow \
  --json
```

Drop `--triage` when the Linear state type is `unstarted` and a worker should start immediately. Assignee is the Hermes profile that should do the work.

From inside an agent that already has the kanban tools, the same card is `kanban_create` (see `kanban-worker` and `kanban-orchestrator`):

```python
kanban_create(
    title="ENG-123: <title>",
    assignee="<profile>",
    body="Linear: <issue url>\nIdentifier: ENG-123\n\n<description>",
    workspace_kind="worktree",
    triage=True,
    idempotency_key="linear:ENG-123",
    skills=["linear", "github-pr-workflow"],
)
```

The worker finishes with `kanban_complete` and puts the link in metadata, using the handoff shape from `kanban-worker`:

```python
kanban_complete(
    summary="ENG-123 shipped",
    metadata={
        "linear_identifier": "ENG-123",
        "pr_url": "<pull request url>",
        "commit": "<sha>",
    },
)
```

Read it back with `hermes kanban show <task_id> --json`.

### Write the link back to Linear

Comment on the issue with the curl mutation from the linear skill. `issueId` is the Linear UUID from the read step (short identifiers such as `ENG-123` also work on `issue(id:)` lookups; `commentCreate` wants the UUID).

```bash
curl -s -X POST https://api.linear.app/graphql \
  -H "Authorization: $LINEAR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "mutation { commentCreate(input: { issueId: \"ISSUE_UUID\", body: \"Hermes kanban <task_id> finished. PR/commit: <url>\" }) { success comment { id body } } }"}' | python3 -m json.tool
```

Check the GraphQL `errors` array. HTTP 200 can still be a failure. If Zapier is connected, use the listed Linear comment action with the same body. Do not delete the issue.

## 3. Airtable record sync

Preset: `zapier-airtable`.

```bash
hermes mcp add zapier-airtable --preset zapier-airtable --auth oauth
```

The `airtable` skill is curl plus `AIRTABLE_API_KEY` and has no MCP server. Keep that path. The token stays in `~/.hermes/.env`. Do not print it. `$BASE_ID` is `app...`, `$TABLE` is a table id or name, `$RECORD_ID` is `rec...`.

This workflow lists and searches records, updates those records, and writes a status field back. Confirm field names with the airtable skill's read-only schema GET if you are unsure of the spelling. Do not create or delete bases, tables, or fields. Do not delete records. Do not pass `typecast: true` to invent new single-select options; the status value must already exist.

### List records that need action

Same URL-encoding pattern as the airtable skill:

```bash
FORMULA="OR({Status}='Todo', {Status}='Needs action')"
ENC=$(python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$FORMULA")
curl -s "https://api.airtable.com/v0/$BASE_ID/$TABLE?filterByFormula=$ENC&maxRecords=20" \
  -H "Authorization: Bearer $AIRTABLE_API_KEY" | python3 -m json.tool
```

Page with `offset` when the response includes one (100 records per page). Zapier alternative: the list or search action from `hermes mcp test zapier-airtable`. Search and list only.

### Update the record and write status back

PATCH merges fields. Unmentioned fields stay as they are. This is the airtable skill's update:

```bash
curl -s -X PATCH "https://api.airtable.com/v0/$BASE_ID/$TABLE/$RECORD_ID" \
  -H "Authorization: Bearer $AIRTABLE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"fields":{"Status":"Done"}}' | python3 -m json.tool
```

Use a status the base already has (`In progress`, `Done`, or whatever the user named). On the Zapier path, call the update-record action with that same field. Skip delete-record and any schema action.

### Cron or a manual run

Cron delivery stays `local` so the job does not post to chat or email. Put the real base id and table in the prompt the user supplies. The schedule below is the template:

```bash
hermes cron create "every 1h" \
  "List Airtable records that need action (Status is Todo or Needs action) in base BASE_ID table TABLE. Update each record through the airtable skill or zapier-airtable MCP tools, then PATCH the Status field. Do not change schema or delete records." \
  --name "airtable-record-sync" \
  --deliver local \
  --skill airtable \
  --skill zapier-mcp-workflows
```

A manual run is the same prompt in a normal Hermes session with the `airtable` skill loaded. `hermes cron list` shows the job. `hermes cron pause <id>` stops it. Do not point `--deliver` at email.

## Lovable — do not wire into this repo

Lovable (https://lovable.dev) is a separate web-app builder. This hermes-agent tree is not a Lovable app. GitHub sync from Lovable creates a new private repository. It cannot attach to this checkout. Do not add Lovable API keys, tokens, accounts, or an MCP preset for Lovable.

Optional later workflow only: a Lovable project syncs to its own new GitHub repo, and that repo's issue and pull request webhooks can hit `hermes webhook subscribe` the same way as any other GitHub repo (section 1 and `webhook-subscriptions`). That path is not part of this repository.

## Common Pitfalls

1. **Using `zapier-github` as the GitHub API.** Issue lists, PR diffs, merges, and `gh` auth stay on `github-auth`, `github-code-review`, `github-pr-workflow`, and `native-mcp`.
2. **Relay posts with no `X-GitHub-Event`.** `--events issues` and `--events pull_request` drop the request. Forward the header and the original JSON body.
3. **Unsigned relay posts.** Copy the subscription secret into Zapier's signature step on the machine that ran `hermes webhook subscribe`. Do not store it in the skill or the repo.
4. **The example chat id.** `-100123456789` is the placeholder already in `webhook-subscriptions`. Replace it with the user's chat id.
5. **Duplicate kanban cards.** Always pass `--idempotency-key linear:<identifier>` (or `idempotency_key` on `kanban_create`).
6. **Airtable schema edits.** This sync writes record fields, especially `Status`. Schema reads are allowed. Schema writes and record deletes are out of scope.
7. **Placeholder ids in commands.** `ENG-123`, `ISSUE_UUID`, `BASE_ID`, `TABLE`, and `RECORD_ID` are stand-ins. Fill them from the read step.
8. **Lovable attached to this checkout.** Sync creates a new repo. Leave this tree alone.

## Verification Checklist

- [ ] Only the preset for the workflow the user asked for was added, with `--preset` and `--auth oauth`.
- [ ] No token, webhook secret, or account password was written into a file or command.
- [ ] GitHub inbound routes use the `webhook-subscriptions` commands for events `issues` and `pull_request`.
- [ ] A private gateway uses Zapier as the POST relay, with `X-GitHub-Event` and an HMAC header.
- [ ] Linear cards use an idempotency key, and the PR or commit URL is a Linear comment.
- [ ] Airtable changes are record PATCH calls that set a status field, from cron `--deliver local` or a manual run.
- [ ] Lovable was not configured.
