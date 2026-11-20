# tweetkit-x — drop-in rule for your AI agent

Copy the block below into your agent's instructions (for example `~/.claude/CLAUDE.md`, a Claude Code agent file,
`AGENTS.md`, `GEMINI.md` or a Cursor rule). Full contract: https://github.com/nsozturk/tweetkit-x/blob/main/AGENTS.md

```markdown
## X (Twitter) via tweetkit-x

tweetkit-x is a free, open-source Python library, CLI and MCP server that posts, deletes and reads on X (Twitter) with your own logged-in web session, including images and threads, with no paid API.

- Use the `tweetkit` MCP server (48 tools) or the `tweetkit` CLI. Call `auth_status` first.
- Auth is the user's X session cookie (`auth_token` + `ct0`). If missing, ask the user to paste the `cookie:`
  request header from a logged-in x.com request (DevTools → Network) into `set_session_cookie`, or point
  `import_cookie_from_file` at a HAR / storage-dump zip. Never print, log or store the cookie anywhere else.
- Every write is public and acts on the user's real account. Before posting, deleting, following, blocking or any
  bulk action, show the exact text, files and ids/handles and wait for an explicit yes. Deletes are irreversible.
- Images: `post_tweet(text, images=[...], alt_texts=[...])` and `post_thread(tweets=[{"text", "images", "alt_texts"}, ...])`
  take up to 4 local files per tweet (absolute paths). The thread is checked before the first tweet is posted, but
  a failure after posting starts leaves the earlier tweets up — report what the result list says was posted.
- Use `dry_run=True` first where offered. On HTTP 429 or a `stop` / `counts.stopped` signal, stop and tell the
  user to wait; never retry in a loop.
- Automating the web session is against X's Terms of Service and can get the account limited or suspended. Say so
  if the user asks for heavy or bulk automation.
```
