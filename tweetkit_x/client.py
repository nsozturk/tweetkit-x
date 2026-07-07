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
    MEDIA_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                   ".gif": "image/gif", ".webp": "image/webp",
                   ".mp4": "video/mp4", ".mov": "video/quicktime", ".m4v": "video/mp4"}

    def upload_media(self, path, media_type=None, alt_text=None):
        """Upload an image / GIF / video and return its media_id.

        Handles INIT/APPEND(chunked)/FINALIZE, async video processing (STATUS
        polling), and optional accessibility `alt_text`.
        """
        import time as _t
        ext = os.path.splitext(path)[1].lower()
        media_type = media_type or self.MEDIA_TYPES.get(ext, "image/png")
        category = ("tweet_video" if media_type.startswith("video")
                    else "tweet_gif" if media_type == "image/gif" else "tweet_image")
        size = os.path.getsize(path)
        mpath = "/i/media/upload.json"
        init = (f"{C.UPLOAD_URL}?command=INIT&total_bytes={size}"
                f"&media_type={media_type.replace('/', '%2F')}&media_category={category}")
        r = self._session.post(init, headers=self._headers("POST", mpath), timeout=self.timeout)
        if r.status_code not in (200, 202):
            raise RuntimeError(f"media INIT {r.status_code}: {r.text[:200]}")
        mid = r.json()["media_id_string"]

        with open(path, "rb") as f:
            data = f.read()
        chunk = 4 * 1024 * 1024
        for idx, off in enumerate(range(0, len(data) or 1, chunk)):
            seg = data[off:off + chunk]
            r = self._session.post(
                f"{C.UPLOAD_URL}?command=APPEND&media_id={mid}&segment_index={idx}",
                headers=self._headers("POST", mpath),
                files={"media": ("blob", seg, "application/octet-stream")}, timeout=self.timeout)
            if r.status_code not in (200, 204):
                raise RuntimeError(f"media APPEND {r.status_code}: {r.text[:200]}")

        r = self._session.post(f"{C.UPLOAD_URL}?command=FINALIZE&media_id={mid}",
                               headers=self._headers("POST", mpath), timeout=self.timeout)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"media FINALIZE {r.status_code}: {r.text[:200]}")

        info = (r.json() or {}).get("processing_info")
        while info and info.get("state") in ("pending", "in_progress"):
            _t.sleep(min(info.get("check_after_secs", 2), 10))
            s = self._session.get(f"{C.UPLOAD_URL}?command=STATUS&media_id={mid}",
                                  headers=self._headers("GET", mpath), timeout=self.timeout)
            info = (s.json() or {}).get("processing_info")
            if info and info.get("state") == "failed":
                raise RuntimeError(f"media processing failed: {info}")

        if alt_text:
            self._session.post(
                C.MEDIA_METADATA_URL,
                data=json.dumps({"media_id": mid, "alt_text": {"text": str(alt_text)[:1000]}}),
                headers=self._headers("POST", "/1.1/media/metadata/create.json",
                                      {"content-type": "application/json"}),
                timeout=self.timeout)
        return mid

    def create_tweet(self, text, media_ids=None, reply_to=None, quote_tweet_id=None):
        """Post one tweet (optionally with media, as a reply, or quoting a tweet)."""
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
        if quote_tweet_id:
            variables["attachment_url"] = f"https://x.com/i/status/{quote_tweet_id}"
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

    def post(self, text, image_path=None, reply_to=None, images=None, alt_texts=None):
        """Post text + optional media. Use `image_path` for one image, or `images`
        for up to 4 (images/GIF/video); `alt_texts` is an optional parallel list.
        Returns {ok,id,url} or {ok:False,error}."""
        paths = list(images) if images else ([image_path] if image_path else [])
        alts = list(alt_texts) if alt_texts else []
        mids = [self.upload_media(p, alt_text=(alts[i] if i < len(alts) else None))
                for i, p in enumerate(paths[:4])] or None
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

    def quote(self, text, quote_tweet_id, image_path=None):
        """Quote-tweet an existing tweet, with optional image."""
        mids = [self.upload_media(image_path)] if image_path else None
        return self.create_tweet(text, mids, quote_tweet_id=quote_tweet_id)

    # ------------------------------------------------------------ engagement
    def _mutation(self, op, variables):
        """POST a GraphQL mutation ({variables, queryId}); returns {ok,...} or {ok:False,error}."""
        qid = C.QUERY_IDS[op]
        path = f"/i/api/graphql/{qid}/{op}"
        payload = {"variables": variables, "queryId": qid}
        r = self._session.post(
            f"{C.GQL_BASE}/{qid}/{op}", data=json.dumps(payload),
            headers=self._headers("POST", path, {"content-type": "application/json"}),
            timeout=self.timeout)
        try:
            j = r.json()
        except Exception:
            return {"ok": False, "status": r.status_code, "error": r.text[:300]}
        if j.get("errors"):
            return {"ok": False, "status": r.status_code,
                    "error": "; ".join(e.get("message", "?") for e in j["errors"])}
        return {"ok": True, "data": j.get("data")}

    def like(self, tweet_id):
        """Like a tweet."""
        return self._mutation("FavoriteTweet", {"tweet_id": str(tweet_id)})

    def unlike(self, tweet_id):
        """Remove a like."""
        return self._mutation("UnfavoriteTweet", {"tweet_id": str(tweet_id)})

    def retweet(self, tweet_id):
        """Repost (retweet) a tweet."""
        return self._mutation("CreateRetweet", {"tweet_id": str(tweet_id), "dark_request": False})

    def unretweet(self, tweet_id):
        """Undo a repost. Pass the id of the ORIGINAL tweet that was retweeted."""
        return self._mutation("DeleteRetweet", {"source_tweet_id": str(tweet_id), "dark_request": False})

    def bookmark(self, tweet_id):
        """Bookmark a tweet (private)."""
        return self._mutation("CreateBookmark", {"tweet_id": str(tweet_id)})

    def unbookmark(self, tweet_id):
        """Remove a bookmark."""
        return self._mutation("DeleteBookmark", {"tweet_id": str(tweet_id)})

    # --------------------------------------------------------------- reading
    def get_tweet(self, tweet_id):
        """Fetch a single tweet by id (TweetResultByRestId). Returns a tweet dict or {ok:False}."""
        qid = C.QUERY_IDS["TweetResultByRestId"]
        path = f"/i/api/graphql/{qid}/TweetResultByRestId"
        variables = {"tweetId": str(tweet_id), "withCommunity": False,
                     "includePromotedContent": False, "withVoice": False}
        params = {"variables": json.dumps(variables),
                  "features": json.dumps(C.USER_TWEETS_FEATURES),
                  "fieldToggles": json.dumps({"withArticleRichContentState": False})}
        r = self._session.get(f"{C.GQL_BASE}/{qid}/TweetResultByRestId", params=params,
                              headers=self._headers("GET", path), timeout=self.timeout)
        if r.status_code != 200:
            return {"ok": False, "status": r.status_code, "error": r.text[:200]}
        tweets, users = {}, {}
        _walk_timeline(r.json(), tweets, users)
        if not tweets:
            return {"ok": False, "error": "tweet not found or unavailable"}
        t = next(iter(tweets.values()))
        handle = users.get(t["author_id"], "i")
        return {"ok": True, **t, "author": handle,
                "url": f"https://x.com/{handle}/status/{t['id']}"}

    def search_x(self, query, product="Top", limit=40):
        """Search ALL of X — the real search, not a local filter (SearchTimeline).

        `product`: 'Top' | 'Latest' | 'People' | 'Media'. Supports X search operators
        (from:user, since:, min_faves:, filter:media, …). Returns a list of tweet dicts.
        """
        qid = C.QUERY_IDS["SearchTimeline"]
        path = f"/i/api/graphql/{qid}/SearchTimeline"
        tweets, users, cursor, pages = {}, {}, None, 0
        while len(tweets) < limit and pages < 20:
            pages += 1
            variables = {"rawQuery": query, "count": 20,
                         "querySource": "typed_query", "product": product}
            if cursor:
                variables["cursor"] = cursor
            params = {"variables": json.dumps(variables),
                      "features": json.dumps(C.USER_TWEETS_FEATURES)}
            r = self._session.get(f"{C.GQL_BASE}/{qid}/SearchTimeline", params=params,
                                  headers=self._headers("GET", path), timeout=self.timeout)
            if r.status_code != 200:
                raise RuntimeError(f"SearchTimeline HTTP {r.status_code}: {r.text[:200]}")
            before = len(tweets)
            next_cursor = _walk_timeline(r.json(), tweets, users)
            if len(tweets) == before or not next_cursor:
                break
            cursor = next_cursor
        out = []
        for t in tweets.values():
            handle = users.get(t["author_id"], "i")
            out.append({**t, "author": handle,
                        "url": f"https://x.com/{handle}/status/{t['id']}"})
        out.sort(key=lambda x: x["created_at_ts"], reverse=True)
        return out[:limit]

    # -------------------------------------------------------- compose (more)
    def post_note(self, text, image_path=None, reply_to=None):
        """Post a long-form (note) tweet — beyond the 280-char limit."""
        qid = C.QUERY_IDS["CreateNoteTweet"]
        path = f"/i/api/graphql/{qid}/CreateNoteTweet"
        mids = [self.upload_media(image_path)] if image_path else []
        media_entities = [{"media_id": m, "tagged_users": []} for m in mids]
        variables = {"tweet_text": text,
                     "media": {"media_entities": media_entities, "possibly_sensitive": False},
                     "semantic_annotation_ids": [], "disallowed_reply_options": None}
        if reply_to:
            variables["reply"] = {"in_reply_to_tweet_id": str(reply_to),
                                  "exclude_reply_user_ids": []}
        payload = {"variables": variables, "features": C.CREATE_TWEET_FEATURES, "queryId": qid}
        r = self._session.post(f"{C.GQL_BASE}/{qid}/CreateNoteTweet", data=json.dumps(payload),
            headers=self._headers("POST", path, {"content-type": "application/json"}),
            timeout=self.timeout)
        return _create_result(r)

    def schedule(self, text, at_epoch, image_path=None):
        """Schedule a tweet for a future unix timestamp (seconds). Returns {ok, scheduled_id}."""
        qid = C.QUERY_IDS["CreateScheduledTweet"]
        path = f"/i/api/graphql/{qid}/CreateScheduledTweet"
        mids = [self.upload_media(image_path)] if image_path else []
        variables = {"post_tweet_request": {
            "auto_populate_reply_metadata": False, "status": text,
            "exclude_reply_user_ids": [], "media_ids": mids}, "execute_at": int(at_epoch)}
        payload = {"variables": variables, "queryId": qid}
        r = self._session.post(f"{C.GQL_BASE}/{qid}/CreateScheduledTweet", data=json.dumps(payload),
            headers=self._headers("POST", path, {"content-type": "application/json"}),
            timeout=self.timeout)
        try:
            j = r.json()
        except Exception:
            return {"ok": False, "status": r.status_code, "error": r.text[:200]}
        if j.get("errors"):
            return {"ok": False, "error": "; ".join(e.get("message", "?") for e in j["errors"])}
        try:
            return {"ok": True, "scheduled_id": j["data"]["tweet"]["rest_id"]}
        except Exception:
            return {"ok": False, "error": r.text[:200]}

    def unschedule(self, scheduled_tweet_id):
        """Cancel a scheduled tweet."""
        return self._mutation("DeleteScheduledTweet",
                              {"scheduled_tweet_id": str(scheduled_tweet_id)})

    # --------------------------------------------------- social graph (v1.1)
    def _v11(self, endpoint, data=None, method="POST"):
        """Call a legacy v1.1 REST endpoint (still live for social-graph actions)."""
        url = f"{C.V11_BASE}/{endpoint}.json"
        path = f"/1.1/{endpoint}.json"
        r = self._session.request(method, url, data=data,
            headers=self._headers(method, path,
                {"content-type": "application/x-www-form-urlencoded"}), timeout=self.timeout)
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text[:200]}
        if r.status_code != 200 or (isinstance(body, dict) and body.get("errors")):
            return {"ok": False, "status": r.status_code, "error": body}
        return {"ok": True}

    def follow(self, username):
        """Follow @username."""
        return self._v11("friendships/create", {"user_id": self.user_id_by_name(username)})

    def unfollow(self, username):
        """Unfollow @username."""
        return self._v11("friendships/destroy", {"user_id": self.user_id_by_name(username)})

    def block(self, username):
        """Block @username."""
        return self._v11("blocks/create", {"user_id": self.user_id_by_name(username)})

    def unblock(self, username):
        """Unblock @username."""
        return self._v11("blocks/destroy", {"user_id": self.user_id_by_name(username)})

    def mute(self, username):
        """Mute @username (silent — they aren't notified)."""
        return self._v11("mutes/users/create", {"user_id": self.user_id_by_name(username)})

    def unmute(self, username):
        """Unmute @username."""
        return self._v11("mutes/users/destroy", {"user_id": self.user_id_by_name(username)})

    def pin(self, tweet_id):
        """Pin one of your tweets to your profile."""
        return self._v11("account/pin_tweet", {"tweet_mode": "extended", "id": str(tweet_id)})

    def unpin(self, tweet_id):
        """Unpin a pinned tweet."""
        return self._v11("account/unpin_tweet", {"tweet_mode": "extended", "id": str(tweet_id)})

    # --------------------------------------------------------- reads (more)
    def _tweets_from_gql(self, op, variables, method="GET", features=None,
                         field_toggles=None, limit=100, max_pages=20):
        qid = C.QUERY_IDS[op]
        path = f"/i/api/graphql/{qid}/{op}"
        tweets, users, cursor, pages = {}, {}, None, 0
        while len(tweets) < limit and pages < max_pages:
            pages += 1
            v = dict(variables)
            if cursor:
                v["cursor"] = cursor
            feats = features or C.USER_TWEETS_FEATURES
            if method == "GET":
                params = {"variables": json.dumps(v), "features": json.dumps(feats)}
                if field_toggles is not None:
                    params["fieldToggles"] = json.dumps(field_toggles)
                r = self._session.get(f"{C.GQL_BASE}/{qid}/{op}", params=params,
                                      headers=self._headers("GET", path), timeout=self.timeout)
            else:
                body = {"variables": v, "features": feats, "queryId": qid}
                if field_toggles is not None:
                    body["fieldToggles"] = field_toggles
                r = self._session.post(f"{C.GQL_BASE}/{qid}/{op}", data=json.dumps(body),
                    headers=self._headers("POST", path, {"content-type": "application/json"}),
                    timeout=self.timeout)
            if r.status_code != 200:
                raise RuntimeError(f"{op} HTTP {r.status_code}: {r.text[:200]}")
            before = len(tweets)
            nxt = _walk_timeline(r.json(), tweets, users)
            if len(tweets) == before or not nxt:
                break
            cursor = nxt
        out = []
        for t in tweets.values():
            handle = users.get(t["author_id"], "i")
            out.append({**t, "author": handle, "url": f"https://x.com/{handle}/status/{t['id']}"})
        out.sort(key=lambda x: x["created_at_ts"], reverse=True)
        return out[:limit]

    def _users_from_gql(self, op, variables, limit=100, max_pages=20):
        qid = C.QUERY_IDS[op]
        path = f"/i/api/graphql/{qid}/{op}"
        users, cursor, pages = {}, None, 0
        while len(users) < limit and pages < max_pages:
            pages += 1
            v = dict(variables)
            if cursor:
                v["cursor"] = cursor
            params = {"variables": json.dumps(v), "features": json.dumps(C.USER_TWEETS_FEATURES)}
            r = self._session.get(f"{C.GQL_BASE}/{qid}/{op}", params=params,
                                  headers=self._headers("GET", path), timeout=self.timeout)
            if r.status_code != 200:
                raise RuntimeError(f"{op} HTTP {r.status_code}: {r.text[:200]}")
            before = len(users)
            nxt = _walk_users(r.json(), users)
            if len(users) == before or not nxt:
                break
            cursor = nxt
        return list(users.values())[:limit]

    def home_timeline(self, following=False, limit=40):
        """Your home feed. following=True → 'Following' (chronological); else 'For You'."""
        if following:
            return self._tweets_from_gql("HomeLatestTimeline",
                {"count": 20, "includePromotedContent": False,
                 "latestControlAvailable": True, "withCommunity": True},
                method="POST", limit=limit)
        return self._tweets_from_gql("HomeTimeline",
            {"count": 20, "includePromotedContent": False, "latestControlAvailable": True,
             "requestContext": "launch", "withCommunity": True}, method="POST", limit=limit)

    def get_replies(self, tweet_id, limit=50):
        """Fetch a tweet's conversation / replies (TweetDetail)."""
        return self._tweets_from_gql("TweetDetail",
            {"focalTweetId": str(tweet_id), "with_rux_injections": False,
             "includePromotedContent": False, "withCommunity": True,
             "withQuickPromoteEligibilityTweetFields": True, "withBirdwatchNotes": True,
             "withVoice": True, "withV2Timeline": True},
            limit=limit, field_toggles={"withArticleRichContentState": False})

    def bookmarks(self, limit=100):
        """Your bookmarked tweets."""
        return self._tweets_from_gql("Bookmarks",
            {"count": 20, "includePromotedContent": False}, limit=limit,
            features={**C.USER_TWEETS_FEATURES, "graphql_timeline_v2_bookmark_timeline": True})

    def user_likes(self, username, limit=100):
        """Tweets a user has liked."""
        return self._tweets_from_gql("Likes",
            {"userId": self.user_id_by_name(username), "count": 20,
             "includePromotedContent": False, "withClientEventToken": False,
             "withBirdwatchNotes": False, "withVoice": True, "withV2Timeline": True}, limit=limit)

    def likers(self, tweet_id, limit=100):
        """Users who liked a tweet."""
        return self._users_from_gql("Favoriters",
            {"tweetId": str(tweet_id), "count": 20, "includePromotedContent": True}, limit=limit)

    def retweeters(self, tweet_id, limit=100):
        """Users who retweeted a tweet."""
        return self._users_from_gql("Retweeters",
            {"tweetId": str(tweet_id), "count": 20, "includePromotedContent": True}, limit=limit)

    def followers(self, username, limit=100):
        """A user's followers."""
        return self._users_from_gql("Followers",
            {"userId": self.user_id_by_name(username), "count": 20,
             "includePromotedContent": False}, limit=limit)

    def following(self, username, limit=100):
        """Accounts a user follows."""
        return self._users_from_gql("Following",
            {"userId": self.user_id_by_name(username), "count": 20,
             "includePromotedContent": False}, limit=limit)

    def notifications(self, limit=40):
        """Your notifications timeline (mentions / engagement)."""
        return self._tweets_from_gql("NotificationsTimeline",
            {"count": 20, "timeline_type": "All"}, limit=limit)

    def user_profile(self, username):
        """Full profile for @username: id, name, bio, counts, verified, created_at."""
        qid = C.QUERY_IDS["UserByScreenName"]
        path = f"/i/api/graphql/{qid}/UserByScreenName"
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
        params = {"variables": json.dumps({"screen_name": username.lstrip("@")}),
                  "features": json.dumps(features)}
        r = self._session.get(f"{C.GQL_BASE}/{qid}/UserByScreenName", params=params,
                              headers=self._headers("GET", path), timeout=self.timeout)
        try:
            res = r.json()["data"]["user"]["result"]
        except Exception:
            return {"ok": False, "error": r.text[:200]}
        lg = res.get("legacy", {}) or {}
        core = res.get("core", {}) or {}
        return {"ok": True, "id": res.get("rest_id"),
                "username": core.get("screen_name") or lg.get("screen_name"),
                "name": core.get("name") or lg.get("name"),
                "bio": lg.get("description"), "location": lg.get("location"),
                "followers": lg.get("followers_count"), "following": lg.get("friends_count"),
                "tweets": lg.get("statuses_count"), "verified": res.get("is_blue_verified"),
                "created_at": core.get("created_at") or lg.get("created_at")}

    # ---------------------------------------------------------- reading (own)
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


def _find_rest_id(node):
    """Find the first tweet rest_id under a *_create GraphQL result."""
    if isinstance(node, dict):
        tr = node.get("tweet_results")
        if isinstance(tr, dict) and isinstance(tr.get("result"), dict) and tr["result"].get("rest_id"):
            return tr["result"]["rest_id"]
        for v in node.values():
            r = _find_rest_id(v)
            if r:
                return r
    elif isinstance(node, list):
        for v in node:
            r = _find_rest_id(v)
            if r:
                return r
    return None


def _create_result(r):
    """Normalize a CreateTweet/CreateNoteTweet HTTP response to {ok,id,url} / {ok:False,error}."""
    try:
        j = r.json()
    except Exception:
        return {"ok": False, "status": r.status_code, "error": r.text[:300]}
    if j.get("errors"):
        return {"ok": False, "status": r.status_code,
                "error": "; ".join(e.get("message", "?") for e in j["errors"])}
    rid = _find_rest_id(j.get("data"))
    if rid:
        return {"ok": True, "id": rid, "url": f"https://x.com/i/status/{rid}"}
    return {"ok": False, "status": r.status_code, "error": r.text[:300]}


def _walk_users(node, out, _cursor=None):
    """Collect User results into `out` (rest_id → user dict); return the bottom cursor."""
    found = _cursor
    if isinstance(node, dict):
        if node.get("__typename") == "User" and node.get("rest_id"):
            lg = node.get("legacy", {}) or {}
            core = node.get("core", {}) or {}
            sn = core.get("screen_name") or lg.get("screen_name")
            if sn:
                out[node["rest_id"]] = {
                    "id": node["rest_id"], "username": sn,
                    "name": core.get("name") or lg.get("name"),
                    "bio": lg.get("description"),
                    "followers": lg.get("followers_count"),
                    "following": lg.get("friends_count"),
                    "verified": node.get("is_blue_verified"),
                    "url": f"https://x.com/{sn}"}
        if node.get("cursorType") == "Bottom" and node.get("value"):
            found = node["value"]
        for v in node.values():
            found = _walk_users(v, out, found)
    elif isinstance(node, list):
        for v in node:
            found = _walk_users(v, out, found)
    return found
