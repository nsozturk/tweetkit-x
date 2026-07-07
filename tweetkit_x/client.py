"""tweetkit-x core client.

Drives X (Twitter) by replaying the browser's own internal endpoints with your
logged-in session cookie — the paid X API is never touched:

  * GraphQL  CreateTweet            post text / replies / threads
  * chunked  media/upload.json      INIT / APPEND / FINALIZE for images
  * GraphQL  DeleteTweet            delete a tweet
  * GraphQL  UserTweets             read a user's timeline (paginated)

The anti-bot `x-client-transaction-id` header is generated with the standalone
`x-client-transaction-id` package. Auth is just your cookie + the public web
bearer + the ct0 CSRF value echoed as `x-csrf-token`.
"""
import json
import os
import re

import requests
from bs4 import BeautifulSoup
from x_client_transaction import ClientTransaction
from x_client_transaction.utils import handle_x_migration, get_ondemand_file_url

from . import constants as C
from .cookie import load_cookie, ct0_of, user_id_of, has_auth, missing_required


class TweetKit:
    """A logged-in X web session you can post / delete / read with.

    >>> tk = TweetKit(keychain_slug="tweetkit")   # or cookie=..., cookie_file=...
    >>> tk.whoami()
    {'ready': True, 'user_id': '1986...', 'ct0_len': 160}
    >>> tk.post("hello world")
    {'ok': True, 'id': '18...', 'url': 'https://x.com/i/status/18...'}
    """

    def __init__(self, cookie=None, *, cookie_file=None, keychain_slug=None, timeout=30):
        self.cookie = load_cookie(cookie=cookie, cookie_file=cookie_file,
                                  keychain_slug=keychain_slug)
        miss = missing_required(self.cookie)
        if miss:
            raise ValueError(f"cookie is missing required value(s): {', '.join(miss)}")
        self.timeout = timeout
        self._ct = None
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": C.UA, "Accept-Language": "en-US,en;q=0.9"})

    # ------------------------------------------------------------------ auth
    def _transaction(self):
        """Lazily build the transaction-id generator (fetches x.com home once)."""
        if self._ct is None:
            home = handle_x_migration(self._session)
            od = requests.get(get_ondemand_file_url(home),
                              headers=dict(self._session.headers), timeout=self.timeout)
            self._ct = ClientTransaction(home, BeautifulSoup(od.text, "html.parser"))
        return self._ct

    def _tid(self, method, path):
        return self._transaction().generate_transaction_id(method=method, path=path)

    def _headers(self, method, path, extra=None):
        h = {
            "authorization": C.BEARER, "cookie": self.cookie,
            "x-csrf-token": ct0_of(self.cookie), "x-twitter-active-user": "yes",
            "x-twitter-auth-type": "OAuth2Session", "x-twitter-client-language": "en",
            "x-client-transaction-id": self._tid(method, path),
            "accept": "*/*", "accept-language": "en-US,en;q=0.9",
            "origin": "https://x.com", "referer": "https://x.com/home",
            "user-agent": C.UA,
            "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"macOS"',
            "sec-fetch-dest": "empty", "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }
        if extra:
            h.update(extra)
        return h

    def whoami(self):
        """Cheap local auth check — no network call."""
        return {"ready": has_auth(self.cookie), "user_id": user_id_of(self.cookie),
                "ct0_len": len(ct0_of(self.cookie))}

    # --------------------------------------------------------------- posting
    def upload_media(self, path, media_type="image/png"):
        """Chunked INIT/APPEND/FINALIZE upload of one image; returns media_id."""
        size = os.path.getsize(path)
        mpath = "/i/media/upload.json"
        init = (f"{C.UPLOAD_URL}?command=INIT&total_bytes={size}"
                f"&media_type={media_type.replace('/', '%2F')}&media_category=tweet_image")
        r = self._session.post(init, headers=self._headers("POST", mpath), timeout=self.timeout)
        if r.status_code not in (200, 202):
            raise RuntimeError(f"media INIT {r.status_code}: {r.text[:200]}")
        mid = r.json()["media_id_string"]

        with open(path, "rb") as f:
            img = f.read()
        r = self._session.post(
            f"{C.UPLOAD_URL}?command=APPEND&media_id={mid}&segment_index=0",
            headers=self._headers("POST", mpath),
            files={"media": ("blob", img, "application/octet-stream")}, timeout=self.timeout)
        if r.status_code not in (200, 204):
            raise RuntimeError(f"media APPEND {r.status_code}: {r.text[:200]}")

        r = self._session.post(f"{C.UPLOAD_URL}?command=FINALIZE&media_id={mid}",
                               headers=self._headers("POST", mpath), timeout=self.timeout)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"media FINALIZE {r.status_code}: {r.text[:200]}")
        return mid

    def create_tweet(self, text, media_ids=None, reply_to=None):
        """Post one tweet (optionally with media, optionally as a reply)."""
        qid = C.QUERY_IDS["CreateTweet"]
        path = f"/i/api/graphql/{qid}/CreateTweet"
        media_entities = [{"media_id": m, "tagged_users": []} for m in (media_ids or [])]
        variables = {
            "tweet_text": text,
            "media": {"media_entities": media_entities, "possibly_sensitive": False},
            "semantic_annotation_ids": [], "disallowed_reply_options": None,
            "semantic_annotation_options": {"composition_signal_1": True, "source": "Htl"},
        }
        if reply_to:
            variables["reply"] = {"in_reply_to_tweet_id": str(reply_to),
                                  "exclude_reply_user_ids": []}
        payload = {"variables": variables, "features": C.CREATE_TWEET_FEATURES, "queryId": qid}
        r = self._session.post(
            f"{C.GQL_BASE}/{qid}/CreateTweet", data=json.dumps(payload),
            headers=self._headers("POST", path, {"content-type": "application/json"}),
            timeout=self.timeout)
        try:
            j = r.json()
        except Exception:
            return {"ok": False, "status": r.status_code, "error": r.text[:300]}
        if j.get("errors"):
            return {"ok": False, "status": r.status_code,
                    "error": "; ".join(e.get("message", "?") for e in j["errors"])}
        try:
            rid = j["data"]["create_tweet"]["tweet_results"]["result"]["rest_id"]
            return {"ok": True, "id": rid, "url": f"https://x.com/i/status/{rid}"}
        except Exception:
            return {"ok": False, "status": r.status_code, "error": r.text[:300]}

    def post(self, text, image_path=None, reply_to=None):
        """Post text + optional image. Returns {ok,id,url} or {ok:False,error}."""
        mids = [self.upload_media(image_path)] if image_path else None
        return self.create_tweet(text, mids, reply_to=reply_to)

    def post_thread(self, items):
        """Post a thread. `items` = list of str, or (text, image_path) tuples.
        Each tweet replies to the previous. Returns the per-tweet result list."""
        results, reply_to = [], None
        for it in items:
            text, img = (it, None) if isinstance(it, str) else (it[0], it[1] if len(it) > 1 else None)
            r = self.post(text, image_path=img, reply_to=reply_to)
            results.append(r)
            if not r.get("ok"):
                break
            reply_to = r["id"]
        return results

    # -------------------------------------------------------------- deleting
    def delete(self, tweet_id):
        """Delete one of your tweets by id. Returns {ok, id} or {ok:False,error}."""
        qid = C.QUERY_IDS["DeleteTweet"]
        path = f"/i/api/graphql/{qid}/DeleteTweet"
        payload = {"variables": {"tweet_id": str(tweet_id), "dark_request": False},
                   "queryId": qid}
        r = self._session.post(
            f"{C.GQL_BASE}/{qid}/DeleteTweet", data=json.dumps(payload),
            headers=self._headers("POST", path, {"content-type": "application/json"}),
            timeout=self.timeout)
        try:
            j = r.json()
        except Exception:
            return {"ok": False, "status": r.status_code, "error": r.text[:300]}
        if j.get("errors"):
            return {"ok": False, "status": r.status_code,
                    "error": "; ".join(e.get("message", "?") for e in j["errors"])}
        return {"ok": True, "id": str(tweet_id)}

    def delete_many(self, tweet_ids):
        """Delete several tweets; returns a list of per-id results."""
        return [dict(self.delete(t), tweet_id=str(t)) for t in tweet_ids]

    # --------------------------------------------------------------- reading
    def user_id_by_name(self, username):
        """Resolve @username → numeric user id via UserByScreenName."""
        qid = C.QUERY_IDS["UserByScreenName"]
        path = f"/i/api/graphql/{qid}/UserByScreenName"
        variables = {"screen_name": username.lstrip("@")}
        features = {"hidden_profile_subscriptions_enabled": True,
                    "rweb_tipjar_consumption_enabled": False,
                    "responsive_web_graphql_exclude_directive_enabled": True,
                    "verified_phone_label_enabled": False,
                    "subscriptions_verification_info_is_identity_verified_enabled": True,
                    "subscriptions_verification_info_verified_since_enabled": True,
                    "highlights_tweets_tab_ui_enabled": True,
                    "responsive_web_twitter_article_notes_tab_enabled": True,
                    "subscriptions_feature_can_gift_premium": True,
                    "creator_subscriptions_tweet_preview_api_enabled": True,
                    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
                    "responsive_web_graphql_timeline_navigation_enabled": True}
        params = {"variables": json.dumps(variables), "features": json.dumps(features)}
        r = self._session.get(f"{C.GQL_BASE}/{qid}/UserByScreenName", params=params,
                              headers=self._headers("GET", path), timeout=self.timeout)
        j = r.json()
        try:
            return j["data"]["user"]["result"]["rest_id"]
        except Exception:
            raise RuntimeError(f"could not resolve @{username}: {r.text[:200]}")

    def get_tweets(self, username=None, limit=200, include_replies=True):
        """Return a list of tweet dicts for a user (default: you).

        Each dict: {id, text, created_at, author_id, author, likes, retweets,
        replies, url}. Paginates until `limit` or the timeline runs out.
        """
        if username:
            uid = self.user_id_by_name(username)
        else:
            uid = user_id_of(self.cookie)
            if not uid:
                raise RuntimeError("no twid in cookie — pass username= explicitly.")

        qid = C.QUERY_IDS["UserTweets"]
        path = f"/i/api/graphql/{qid}/UserTweets"
        tweets, users, cursor, seen_pages = {}, {}, None, 0
        while len(tweets) < limit and seen_pages < 40:
            seen_pages += 1
            variables = {"userId": uid, "count": 40, "includePromotedContent": True,
                         "withQuickPromoteEligibilityTweetFields": True, "withVoice": True}
            if cursor:
                variables["cursor"] = cursor
            params = {"variables": json.dumps(variables),
                      "features": json.dumps(C.USER_TWEETS_FEATURES),
                      "fieldToggles": json.dumps(C.USER_TWEETS_FIELD_TOGGLES)}
            r = self._session.get(f"{C.GQL_BASE}/{qid}/UserTweets", params=params,
                                  headers=self._headers("GET", path), timeout=self.timeout)
            if r.status_code != 200:
                raise RuntimeError(f"UserTweets HTTP {r.status_code}: {r.text[:200]}")
            j = r.json()
            before = len(tweets)
            next_cursor = _walk_timeline(j, tweets, users)
            if len(tweets) == before or not next_cursor:
                break
            cursor = next_cursor

        # resolve author handles + build final list
        out = []
        for t in tweets.values():
            handle = users.get(t["author_id"], "i")
            out.append({**t, "author": handle,
                        "url": f"https://x.com/{handle}/status/{t['id']}"})
        out.sort(key=lambda x: x["created_at_ts"], reverse=True)
        if not include_replies:
            out = [t for t in out if not t["is_reply"]]
        return out[:limit]

    def search(self, query, username=None, limit=200, regex=False, include_replies=True):
        """Filter a user's tweets (default: you) by substring or regex.

        This is a *local* filter over `get_tweets` — X's paid search API is not
        used. Great for "find my tweets that mention X".
        """
        tweets = self.get_tweets(username=username, limit=max(limit, 200),
                                 include_replies=include_replies)
        if regex:
            pat = re.compile(query, re.I)
            matched = [t for t in tweets if pat.search(t["text"])]
        else:
            q = query.lower()
            matched = [t for t in tweets if q in t["text"].lower()]
        return matched[:limit]


# --------------------------------------------------------------------------- #
def _epoch(created_at):
    """Twitter 'Sat Jun 06 18:34:39 +0000 2026' → sortable epoch (best effort)."""
    import calendar, time
    try:
        return calendar.timegm(time.strptime(created_at, "%a %b %d %H:%M:%S +0000 %Y"))
    except Exception:
        return 0


def _walk_timeline(node, tweets, users, _cursor=None):
    """Recursively collect tweet 'legacy' objects, user handles, and the bottom cursor."""
    found_cursor = _cursor
    if isinstance(node, dict):
        # user handle lives in `core.screen_name` (new payloads) or
        # `legacy.screen_name` (older ones) — capture whichever is present.
        if node.get("__typename") == "User" and node.get("rest_id"):
            sn = None
            if isinstance(node.get("core"), dict):
                sn = node["core"].get("screen_name")
            if not sn and isinstance(node.get("legacy"), dict):
                sn = node["legacy"].get("screen_name")
            if sn:
                users[node["rest_id"]] = sn
        lg = node.get("legacy")
        if isinstance(lg, dict) and "full_text" in lg:
            tid = lg.get("id_str") or node.get("rest_id")
            if tid:
                tweets[tid] = {
                    "id": tid, "text": lg.get("full_text", ""),
                    "created_at": lg.get("created_at", ""),
                    "created_at_ts": _epoch(lg.get("created_at", "")),
                    "author_id": lg.get("user_id_str"),
                    "likes": lg.get("favorite_count"), "retweets": lg.get("retweet_count"),
                    "replies": lg.get("reply_count"),
                    "is_reply": bool(lg.get("in_reply_to_status_id_str")),
                }
        if node.get("cursorType") == "Bottom" and node.get("value"):
            found_cursor = node["value"]
        for v in node.values():
            found_cursor = _walk_timeline(v, tweets, users, found_cursor)
    elif isinstance(node, list):
        for v in node:
            found_cursor = _walk_timeline(v, tweets, users, found_cursor)
    return found_cursor
