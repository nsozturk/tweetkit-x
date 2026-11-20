"""No-network self-check for the bell / bulk / suggestion-store logic.

    python tests/test_bell_suggestions.py      (or: pytest tests/)
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tweetkit_x import store  # noqa: E402
from tweetkit_x.client import TweetKit, journal_done, stop_reason  # noqa: E402


def test_stop_reason():
    assert stop_reason(429, None) == "HTTP 429 rate limited"
    assert "follow limit" in stop_reason(403, {"errors": [{"code": 161, "message": "x"}]})
    assert "locked" in stop_reason(403, {"errors": [{"code": 326}]})
    assert stop_reason(404, {"errors": [{"code": 50}]}) is None
    assert stop_reason(200, {"ok": 1}) is None


def _fake_tk(states, results):
    tk = TweetKit.__new__(TweetKit)  # no cookie / network
    tk.friendship = lambda n: states[n.lower()]
    tk.follow = lambda n, notify=False, dry_run=False: results.get(n.lower(), {"ok": True})
    tk.set_notifications = lambda n, on, kind="posts", dry_run=False, user_id=None: {"ok": True}
    tk.BULK_WRITE_DELAY = tk.BULK_READ_DELAY = (0, 0)
    return tk


def _state(following=False, bell=False, requested=False):
    return {"ok": True, "user_id": "1", "following": following, "follow_requested": requested,
            "notifications": bell, "live_notifications": False}


def test_bulk_resume_skip_and_stop():
    d = tempfile.mkdtemp()
    j = os.path.join(d, "follow.jsonl")
    states = {"a": _state(), "b": _state(following=True, bell=True),
              "c": _state(following=True), "d": _state(), "e": _state()}
    results = {"d": {"ok": False, "status": 429, "stop": "HTTP 429 rate limited"}}
    tk = _fake_tk(states, results)
    r = tk.bulk_follow(["a", "@B", "c", "d", "e", "a"], journal_path=j,
                       capture_suggestions=False, log=lambda m: None)
    assert r["counts"] == {"done": 2, "skipped": 1, "stopped": 1}, r  # a done, b skipped, c bell, d stop
    assert r["left"] == 1  # e never reached
    assert journal_done(j) == {"a", "b", "c"}
    # re-run after the limit clears: only d and e are attempted
    results.clear()
    seen = []
    tk.follow = lambda n, notify=False, dry_run=False: seen.append(n) or {"ok": True}
    r = tk.bulk_follow(["a", "b", "c", "d", "e"], journal_path=j, capture_suggestions=False,
                       log=lambda m: None)
    assert seen == ["d", "e"] and r["counts"] == {"done": 2}, (seen, r)
    with open(j, "a") as f:
        f.write('{"unit": "torn"')  # crash mid-line must be ignored
    assert "torn" not in journal_done(j)


def test_dry_run_journal_is_separate():
    d = tempfile.mkdtemp()
    j = os.path.join(d, "follow.jsonl")
    tk = _fake_tk({"x": _state()}, {"x": {"ok": True, "dry_run": True}})
    r = tk.bulk_follow(["x"], journal_path=j, dry_run=True, log=lambda m: None)
    assert r["journal"] == j + ".dryrun.jsonl" and not os.path.exists(j)


def test_store_append_only():
    db = store.connect(os.path.join(tempfile.mkdtemp(), "s.sqlite"))
    u = {"id": "7", "username": "alice", "name": "A", "bio": "hi", "followers": 5,
         "following": 1, "verified": True, "token": "t"}
    for _ in range(2):  # a re-fetch adds rows, never overwrites
        store.save_fetch(db, source="follow", method="GET", url="u", params={"a": 1}, status=200,
                         body='[{"user": 1}]', users=[u], for_user_id="9", for_username="hf")
    assert db.execute("SELECT count(*) FROM blobs").fetchone()[0] == 1  # same body, one blob
    assert len(store.list_suggestions(db, distinct=False)) == 2
    rows = store.list_suggestions(db, for_username="@HF", distinct=True)
    assert len(rows) == 1 and rows[0]["username"] == "alice" and rows[0]["verified"] == 1
    out = os.path.join(tempfile.mkdtemp(), "x.json")
    assert store.export(db, out, distinct=True) == 1 and json.load(open(out))[0]["for_username"] == "hf"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
