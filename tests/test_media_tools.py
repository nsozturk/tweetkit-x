"""No-network self-check for media in post_tweet / post_thread (client and MCP tools).

    python tests/test_media_tools.py      (or: pytest tests/)
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tweetkit_x import mcp_server  # noqa: E402
from tweetkit_x.client import TweetKit  # noqa: E402


def _fake_tk():
    """A TweetKit with no cookie and no network: records uploads and tweets."""
    tk = TweetKit.__new__(TweetKit)
    tk.uploads, tk.tweets = [], []

    def upload_media(path, media_type=None, alt_text=None):
        tk.uploads.append((os.path.basename(path), alt_text))
        return "m%d" % len(tk.uploads)

    def create_tweet(text, media_ids=None, reply_to=None, quote_tweet_id=None):
        tk.tweets.append((text, media_ids, reply_to))
        return {"ok": True, "id": "t%d" % len(tk.tweets), "url": "https://x.com/i/status/t%d" % len(tk.tweets)}

    tk.upload_media, tk.create_tweet = upload_media, create_tweet
    return tk


def _files(tmp, n):
    paths = []
    for i in range(n):
        p = os.path.join(tmp, "img%d.png" % i)
        with open(p, "wb") as f:
            f.write(b"\x89PNG fake")
        paths.append(p)
    return paths


def test_thread_items_validation():
    with tempfile.TemporaryDirectory() as tmp:
        a, b = _files(tmp, 2)
        items = TweetKit.thread_items(["one", ("two", a), {"text": "three", "images": [a, b], "alt_texts": ["A"]}])
        assert [len(p) for _, p, _ in items] == [0, 1, 2] and items[2][2] == ["A"]
        for bad, msg in [([{"text": "x", "images": [a] * 5}], "at most 4"),
                         ([{"text": "x", "images": [os.path.join(tmp, "nope.png")]}], "not found"),
                         (["ok", {"text": " "}], "tweet 2: empty text")]:
            try:
                TweetKit.thread_items(bad)
                raise AssertionError("expected ValueError: " + msg)
            except ValueError as exc:
                assert msg in str(exc), exc


def test_mcp_post_tweet_images():
    with tempfile.TemporaryDirectory() as tmp:
        a, b = _files(tmp, 2)
        tk = _fake_tk()
        mcp_server._get_tk = lambda: (tk, None)
        r = mcp_server.post_tweet("hello", images=[a, b], alt_texts=["first"])
        assert r["ok"] and tk.uploads == [("img0.png", "first"), ("img1.png", None)]
        assert tk.tweets == [("hello", ["m1", "m2"], None)]
        r = mcp_server.post_tweet("legacy", image_path=a, reply_to="99")
        assert r["ok"] and tk.tweets[-1] == ("legacy", ["m3"], "99")
        r = mcp_server.post_tweet("bad", images=[os.path.join(tmp, "nope.png")])
        assert not r["ok"] and "not found" in r["error"] and len(tk.tweets) == 2  # nothing posted


def test_mcp_post_thread_images():
    with tempfile.TemporaryDirectory() as tmp:
        a, b, c = _files(tmp, 3)
        tk = _fake_tk()
        mcp_server._get_tk = lambda: (tk, None)
        out = mcp_server.post_thread(["1/ intro", {"text": "2/ two pics", "images": [a, b], "alt_texts": ["x", "y"]},
                                      {"text": "3/ one", "images": [c]}])
        assert [r["ok"] for r in out] == [True, True, True]
        assert tk.tweets == [("1/ intro", None, None), ("2/ two pics", ["m1", "m2"], "t1"), ("3/ one", ["m3"], "t2")]
        assert tk.uploads == [("img0.png", "x"), ("img1.png", "y"), ("img2.png", None)]
        # a bad file anywhere in the thread: nothing is posted at all
        before = len(tk.tweets)
        out = mcp_server.post_thread(["ok", {"text": "bad", "images": [os.path.join(tmp, "nope.png")]}])
        assert out[0]["ok"] is False and "tweet 2" in out[0]["error"] and len(tk.tweets) == before


if __name__ == "__main__":
    test_thread_items_validation()
    test_mcp_post_tweet_images()
    test_mcp_post_thread_images()
    print("media tools ok")
