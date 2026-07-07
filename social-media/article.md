---
title: "Introducing tweetkit-x: post, delete & read on X from Python and MCP — no paid API"
published: false
tags: python, ai, opensource, mcp
cover_image: https://raw.githubusercontent.com/nsozturk/tweetkit-x/main/assets/header.png
canonical_url: https://github.com/nsozturk/tweetkit-x
---

**Introducing tweetkit-x** — a tiny Python library *and* an MCP server that lets you post, delete, and read on X (Twitter) using your own logged-in web session. No paid API, no developer app, no OAuth dance. Just your session cookie.

```bash
pip install tweetkit-x
```

- **GitHub:** https://github.com/nsozturk/tweetkit-x
- **PyPI:** https://pypi.org/project/tweetkit-x/
- **Official MCP Registry:** `io.github.nsozturk/tweetkit-x`

---

## The itch

It started, as these things do, with a chore: I wanted to delete a pile of old `$XMR` price-bot tweets from my account. So I reached for the X API — and hit a wall:

```
402 Payment Required — "credits depleted"
```

Since **February 6, 2026**, X's API has **no free tier for new developers**. It's pay-per-use: roughly **$0.015 per post**, **~$0.20 per post that contains a link**, plus per-read charges. For the simple act of cleaning up *my own* timeline — or running a small bot that posts *my own* content — that's a recurring bill for something my browser already does for free, thousands of times a day.

So I did the obvious thing: I skipped the API.

## The idea: replay what the browser already does

When you click **Post**, **Delete**, or scroll your profile on x.com, your browser fires a handful of internal HTTP calls — GraphQL mutations and queries, authenticated with the session cookie you already have. tweetkit-x reproduces those calls 1:1. No headless browser, no Selenium; just `requests` and the cookie that's already in your jar.

The result is a small kit that does the full lifecycle:

- **✍️ Post** — text, images, replies, and full threads
- **🗑️ Delete** — one tweet, many, or "find matching and delete"
- **📖 Read** — your own timeline or anyone's, paginated
- **🔎 Search** — local substring/regex filtering over a timeline (great for cleanup)

```python
from tweetkit_x import TweetKit

tk = TweetKit(keychain_slug="tweetkit")

tk.post("hello from tweetkit-x 👋")
tk.post_thread(["1/ intro", "2/ more", ("3/ chart", "chart.png")])

# find your old tweets and delete them
hits = tk.search(r"xmr|monero", regex=True)
tk.delete_many([t["id"] for t in hits])
```

There's a one-line CLI too:

```bash
tweetkit post "just some text"
tweetkit search "xmr|monero" --regex
tweetkit delete 2063240404980445603
```

## The part I'm most excited about: it's an MCP server

tweetkit-x ships a first-class **MCP (Model Context Protocol) server**. That means you can drop it into **Claude Desktop, Claude Code, or Cursor** and drive X in plain language:

> **You:** find my old $XMR tweets and delete them
>
> **Claude:** → `search_my_tweets("xmr|monero", regex=true)` — 15 found
> → `delete_tweets([ … ])` — ✓ 15 removed

Ten tools are exposed — `post_tweet`, `post_thread`, `delete_tweet(s)`, `get_my_tweets`, `get_user_tweets`, `search_my_tweets`, plus friction-free auth tools (`set_session_cookie`, `import_cookie_from_file`, `auth_status`). Crucially, the auth tools **explain what each value is** and let you set it up with a single paste — the assistant never has to guess.

Setup is one command:

```bash
claude mcp add tweetkit -s user \
  -e TWEETKIT_COOKIE_KEYCHAIN=tweetkit -- tweetkit-mcp
```

And because it's published to the **official MCP registry**, it automatically propagates to the wider MCP ecosystem (Smithery, Glama, PulseMCP, and friends).

## Auth without the pain

The only secret tweetkit needs is your **session cookie**, which must contain two values:

- `auth_token` — your login/session token (HttpOnly, so a `document.cookie` copy won't include it)
- `ct0` — the CSRF token, echoed back as `x-csrf-token`

You can grab it three ways, whichever is least annoying for you:

1. **Paste the `Cookie:` header** — F12 → Network → click any x.com request → copy the `cookie:` header. One paste.
2. **An F12 "Preserve log" HAR file** — `tweetkit import --file x.com.har`.
3. **A storage-dump zip** — a browser extension that exports `cookies.json`.

It's stored `chmod 600` in `~/.config/tweetkit/cookie.txt` or your **macOS Keychain**, and it **never leaves your machine**. tweetkit never prints the value back.

## How it works, briefly

Three moving parts reproduce the browser's behavior:

1. **`x-client-transaction-id`** — X's anti-bot header, derived from the page's `ondemand.s` JS. Generated with the standalone `x-client-transaction-id` package.
2. **Media upload** — chunked `INIT` → `APPEND` → `FINALIZE` against `upload.x.com`.
3. **GraphQL** — `CreateTweet`, `DeleteTweet`, and `UserTweets`, authenticated with your cookie + the public web bearer + the `ct0` CSRF value.

The GraphQL query IDs live in one file and are easy to refresh from a fresh HAR when X ships a new web build.

## Honest limitations

tweetkit is deliberately small. Right now it does **not** do video upload, likes/retweets/bookmarks/follows, DMs, global X search, polls, or scheduling. It works through your **own** session, so you're bound by normal human-account rate limits — use it kindly.

And the big one: **automating your web session is against X's Terms of Service.** This is a grey-area tool for personal automation. Your account, your risk. It's MIT-licensed and provided as-is.

## Try it

```bash
pip install tweetkit-x        # library + CLI
pip install "tweetkit-x[mcp]" # + the MCP server
```

- ⭐ **GitHub:** https://github.com/nsozturk/tweetkit-x
- 📦 **PyPI:** https://pypi.org/project/tweetkit-x/

---

*P.S. — the launch thread announcing this post was published with tweetkit-x itself. A tool dogfooding its own post engine felt like the only honest way to ship it. 🐝*
