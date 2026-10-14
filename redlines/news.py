"""News stories: the feed AIRO reads when AI news breaks.

Step 1 of three (2026-10-13 brief; the 2026-10-09 meeting asked for AIRO to be
where people look when big AI news breaks). Items come from RSS/Atom feeds
(data/news_feeds.json); `reduce` folds them into STORIES, one per real-world
event. The two later steps are out of scope here and only shape the record:
a screen (does a story move the latest AIRO forecast, per cause family in
data/autoarc_ladder.json) and an explanation of the stories it flags.

WHY A FEED AND NOT A SEARCH. Generic search queries found 1 of 9 held-out
incidents from the previous quarter on every backend tried
(code/recency_backend_recall.py, results/experiments/recency_backends/
2026-09-02.json). A feed sees what was published, whether or not anyone
thought to ask for it. The cost is that a feed shows only its latest 10-100
items, so history exists only if something polls: `poll` is free (no keys)
and is meant to run every ~15 minutes.

STATE lives in `.local/news/` (gitignored; the repo is public and never holds
article text):
  items.jsonl      one row per item, first sighting; a later sighting of the
                   same item in another feed appends {"id", "also_in", "at"}
  fetches.jsonl    one row per feed fetch: status, entries, new items, error
  decisions.jsonl  every Jev decision, append-only (see `reduce`)
  stories.json     the stories, rebuilt from the two logs above on each reduce

ONE ITEM, ONE URL. Items with the same canonical URL (`canonical_url`) are the
same item: no model call. Google News links (the only route to Reuters, which
publishes no RSS) are redirects; `resolve_google_news` turns them into the
Reuters URL so a Reuters story found by search later is still the same item.

ONE EVENT, ONE STORY: see `reduce`.

Stdlib only, like the rest of the pipeline: urllib for the feeds and for Jev's
one POST.
"""
import hashlib
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FEEDS_PATH = os.path.join(ROOT, "data", "news_feeds.json")
# AIRO_NEWS_DIR moves it: the poller on airo-dev keeps its history outside any
# checkout, so ending a session does not end the history.
STATE_DIR = os.environ.get("AIRO_NEWS_DIR") or os.path.join(ROOT, ".local", "news")

USER_AGENT = "Mozilla/5.0 (compatible; airo-news/0.1; +https://github.com/forecastingresearch/airo)"
FETCH_TIMEOUT = 30
SUMMARY_CHARS = 600   # what an item keeps of a feed's description, after HTML is stripped


# ---------------------------------------------------------------- feeds

def load_feeds(path=FEEDS_PATH):
    return json.load(open(path))["feeds"]


def http_get(url, timeout=FETCH_TIMEOUT, data=None, headers=None):
    """(status, body bytes, error). Never raises: a feed that is down is a row
    in fetches.jsonl, not a failed poll."""
    req = urllib.request.Request(url, data=data,
                                 headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), None
    except urllib.error.HTTPError as e:
        return e.code, b"", f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, b"", f"{type(e).__name__}: {e}"


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _text(el):
    return (el.text or "").strip() if el is not None else ""


def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def parse_time(s):
    """An ISO-8601 UTC string from an RSS (RFC 822) or Atom (RFC 3339) date,
    or None."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_feed(body):
    """The entries of an RSS 2.0 or Atom document, as
    [{title, link, summary, published, guid, categories}]. Raises
    ET.ParseError on a document that is not XML (a block page, say)."""
    root = ET.fromstring(body)
    out = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        e = {"title": "", "link": "", "summary": "", "published": None, "guid": "",
             "categories": []}
        updated = None
        for c in el:
            tag = _local(c.tag)
            if tag == "title":
                e["title"] = strip_html(_text(c))
            elif tag == "link":
                # RSS: <link>url</link>. Atom: <link href rel>. NYT carries both,
                # the Atom one empty; the first non-empty alternate wins.
                href = c.get("href") or _text(c)
                if href and not e["link"] and c.get("rel", "alternate") == "alternate":
                    e["link"] = href
            elif tag in ("description", "summary") and not e["summary"]:
                e["summary"] = strip_html(_text(c))
            elif tag in ("pubDate", "published", "date") and not e["published"]:
                e["published"] = parse_time(_text(c))
            elif tag == "updated":
                updated = parse_time(_text(c))
            elif tag in ("guid", "id"):
                e["guid"] = _text(c)
            elif tag == "category":
                v = c.get("term") or _text(c)
                if v:
                    e["categories"].append(v)
        e["published"] = e["published"] or updated   # Atom: <updated> only when unpublished
        if not e["link"] and e["guid"].startswith("http"):
            e["link"] = e["guid"]
        if e["title"] or e["link"]:
            out.append(e)
    return out


def canonical_url(url):
    """The URL two sightings of one article share: https, lower-case host with
    no `www.`, no fragment, no trailing slash, and NO QUERY STRING, because on
    news sites the query is tracking (FT's `?syn-25`, `utm_*`). The one
    exception is a bare path (`/?p=123`), where the query is the article."""
    p = urllib.parse.urlsplit((url or "").strip())
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = p.path.rstrip("/")
    query = p.query if path in ("", "/") else ""
    return urllib.parse.urlunsplit(("https", host, path, query, ""))


def item_id(canonical):
    return hashlib.sha1(canonical.encode()).hexdigest()[:16]


# ---------------------------------------------------------- Google News

GNEWS_DECODE_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"


def resolve_google_news(link, get=http_get):
    """The publisher URL behind a news.google.com/rss/articles/... link, or
    None. Google serves no redirect: the article page carries a signature
    (data-n-a-sg, data-n-a-ts) that its own batchexecute endpoint exchanges
    for the URL. Two requests per new item. Unofficial and liable to break;
    when it does, the item keeps its Google link and is still de-duplicated
    by it (open question for Nick: is Google News acceptable for Reuters?)."""
    status, body, err = get(link)
    if err or not body:
        return None
    page = body.decode("utf-8", "replace")
    m = {k: re.search(rf'data-n-a-{k}="([^"]+)"', page) for k in ("id", "ts", "sg")}
    if not all(m.values()):
        return None
    inner = ["garturlreq",
             [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None,
               None, None, None, 0, 1], "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
             m["id"][1], int(m["ts"][1]), m["sg"][1]]
    form = urllib.parse.urlencode(
        {"f.req": json.dumps([[["Fbv4je", json.dumps(inner), None, "generic"]]])}).encode()
    status, body, err = get(GNEWS_DECODE_URL, data=form, headers={
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"})
    if err:
        return None
    hit = re.search(r'\\"garturlres\\",\\"(https?://[^"\\]+)\\"', body.decode("utf-8", "replace"))
    return hit[1] if hit else None


def _gnews_title(title, source):
    """Google News appends ' - Reuters' to every headline."""
    suffix = f" - {source}"
    return title[:-len(suffix)] if title.endswith(suffix) else title


# ---------------------------------------------------------------- state

def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass   # a torn last line from a killed poll; the next append is whole
    return rows


def append_jsonl(path, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def load_items(state_dir=STATE_DIR):
    """{id: item} in first-sighting order, with `feeds` the list of every feed
    that has carried it."""
    items = {}
    for r in read_jsonl(os.path.join(state_dir, "items.jsonl")):
        if "also_in" in r:
            it = items.get(r["id"])
            if it and r["also_in"] not in it["feeds"]:
                it["feeds"].append(r["also_in"])
        else:
            items[r["id"]] = dict(r, feeds=[r["feed"]])
    for r in read_jsonl(os.path.join(state_dir, FULLTEXT_LOG)):   # the newest extract wins
        if r["item"] in items and r.get("text"):
            items[r["item"]]["text"] = r["text"]
    for it in items.values():   # no standfirst in the feed: the article's opening paragraph
        if not it.get("summary") and it.get("text"):
            it["summary"], it["summary_from"] = lede(it["text"], it["title"]), "article"
    return items


# ----------------------------------------------------------------- poll

def poll(feeds=None, state_dir=STATE_DIR, get=http_get, resolve=resolve_google_news, now=None):
    """Fetch every feed once and append what is new. Free: no keys, no model.
    Returns the fetch rows it logged."""
    feeds = feeds if feeds is not None else load_feeds()
    now = now or _now()
    items = load_items(state_dir)
    by_url = {it["url"]: it for it in items.values()}
    by_link = {it["link"]: it for it in items.values()}
    new_rows, fetch_rows = [], []
    for feed in feeds:
        t0 = time.time()
        status, body, err = get(feed["url"])
        row = {"at": now, "feed": feed["id"], "status": status, "bytes": len(body),
               "entries": 0, "new": 0}
        entries = []
        if not err:
            try:
                entries = parse_feed(body)
            except ET.ParseError as e:
                err = f"not a feed: {e}"
        row["entries"] = len(entries)
        for e in entries:
            link = e["link"]
            seen = by_link.get(link)
            if seen is None:
                url = link
                if feed.get("resolve") == "google_news":
                    url = resolve(link) or link
                seen = by_url.get(canonical_url(url))
                if seen is None:
                    canon = canonical_url(url)
                    title = e["title"]
                    if feed.get("resolve") == "google_news":
                        title = _gnews_title(title, feed["source"])
                    summary = e["summary"][:SUMMARY_CHARS]
                    if feed.get("resolve") == "google_news":
                        summary = ""   # Google News's description is the headline again
                    it = {"id": item_id(canon), "feed": feed["id"], "source": feed["source"],
                          "title": title, "summary": summary, "url": canon, "link": link,
                          "published": e["published"], "first_fetched": now,
                          "categories": e["categories"][:12],
                          "open_access": bool(feed.get("open_access")),
                          "ai_only_feed": bool(feed.get("ai_only"))}
                    new_rows.append(it)
                    seen = dict(it, feeds=[feed["id"]])
                    items[it["id"]] = seen
                    by_url[canon] = seen
                    row["new"] += 1
            by_link[link] = seen
            if feed["id"] not in seen["feeds"]:
                seen["feeds"].append(feed["id"])
                new_rows.append({"id": seen["id"], "also_in": feed["id"], "at": now})
        if err:
            row["error"] = err
        row["seconds"] = round(time.time() - t0, 2)
        fetch_rows.append(row)
    append_jsonl(os.path.join(state_dir, "items.jsonl"), new_rows)
    append_jsonl(os.path.join(state_dir, "fetches.jsonl"), fetch_rows)
    return fetch_rows


# --------------------------------------------------------------- reduce
#
# ONE REAL-WORLD EVENT IS ONE STORY. Twelve write-ups of one incident are one
# story; two different OpenAI announcements on the same day are two. Items are
# folded in a fixed order (first fetched, then published, then id), and for
# each one:
#
#   1. AI GATE, only for an item no AI-only feed has carried (NYT Technology):
#      one Jev Noul, "is this item about AI". Below AI_AT it is dropped.
#   2. SHORTLIST, in code: the stories whose span is within WINDOW_HOURS of
#      the item, ranked by word overlap with it, at most SHORTLIST. None means
#      a new story with no model call.
#   3. MATCH: one Jev call, one Noul per candidate story ("does the new item
#      report the same real-world event as this story"), all fanned out against
#      the same state. The best candidate at or above SAME_AT takes the item;
#      otherwise it seeds a new story.
#
# WHY NOULS AND NOT A CHOICE. A Choice over [candidates + new] is one
# normalised distribution, but jev-1.13 leans toward a Choice's FIRST option
# (docs: model-jaggedness/jev-1.13, "Choice option order"), and a shortlist
# sorted by similarity puts the likeliest merge first, so the bias would land
# on exactly the decision that matters. One Noul per candidate is a literal,
# single-hop yes/no with the state holding only the new item and the question
# holding only one story (docs: large state is a distractor), it is the shape
# the docs' own duplicate check uses (primitives/noul, structured instructions),
# each pair gets its own probability (so an item that matches two stories shows
# up, and the close calls can be audited and re-thresholded), and "new" is a
# rule in code (no candidate >= SAME_AT) rather than an option Jev weighs.
#
# FOLLOW-UPS are a judgment call for Nick (an official response, a revised
# casualty count). The same call asks, per candidate, a second Noul: is the new
# item a later development of that story's event. It does not decide anything
# yet: a follow-up that is not the "same event" seeds its own story and is
# linked as `related`, so the report can show real examples before a policy
# is chosen.
#
# THE LOG. Every decision (gate or match) is appended to decisions.jsonl with
# the item, the candidates, every probability, the model and the thresholds in
# force. stories.json is never edited: it is rebuilt by folding the items over
# the log, so the fold replays deterministically and a threshold change is a
# replay (`reduce --replay`), not a re-run. A logged match is reused when its
# candidate set is the one the fold arrives at; when an earlier change has
# altered the candidates, the item is asked again (or, in replay, decided from
# the probabilities logged for the candidates that are still there).

WINDOW_HOURS = 72       # a story is open to items within this long of its span
SHORTLIST = 20          # at most this many candidate stories per Jev call
MIN_OVERLAP = 1         # shared content words a candidate needs to be shortlisted
SAME_AT = 0.5           # p(same event) at which an item joins a story
AI_AT = 0.5             # p(about AI) at which a gated item is kept
FOLLOWUP_AT = 0.5       # p(follow-up) at which a new story is linked as related
STORY_REPORTS = 3       # member items a story shows Jev: its first and latest
THRESHOLDS = {"window_hours": WINDOW_HOURS, "shortlist": SHORTLIST, "same_at": SAME_AT,
              "ai_at": AI_AT, "followup_at": FOLLOWUP_AT}

# The cause families a later screen will judge each story against
# (data/autoarc_ladder.json causes[].key). The story record carries an empty
# `screen` keyed by them so the next stage fills a slot rather than a schema.
CAUSES = ("ai", "bio", "cyber", "misalign")

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"

AI_Q = {
    "type": "noul",
    "instructions": "Is `item` about artificial intelligence?",
    "criteria": {
        "true": "Yes: artificial intelligence is a main subject of the item: AI models, "
                "chatbots or agents, AI companies or labs, AI chips and data centres, AI "
                "policy or regulation, or harms, incidents or misuse involving AI.",
        "false": "No: the item is about something else (gadgets, social media, space, "
                 "telecoms, entertainment, business) and AI is absent or mentioned only "
                 "in passing.",
    },
}

SAME_Q = "Does `new_item` report the same real-world event as the reports in `story`?"
SAME_CRITERIA = {
    "true": "Yes: they are about one specific event, the same announcement, release, "
            "incident, attack, ruling, deal, report or publication, even if the outlets, "
            "wording, angle or details differ.",
    "false": "No: they are about different events, even if they involve the same company, "
             "product, person or topic. Two different announcements by the same company "
             "are two events. A general analysis or opinion piece about a topic is not the "
             "same event as a report of one specific development.",
}
FOLLOWUP_Q = ("Does `new_item` report a later development of the event in `story`: a "
              "response, reaction, investigation, correction, update or consequence that "
              "came after that event?")
FOLLOWUP_CRITERIA = {
    "true": "Yes: `new_item` is about something that happened because of, or after, the "
            "event in `story`, such as an official response, a revised figure, a lawsuit "
            "or a policy reaction.",
    "false": "No: `new_item` reports the original event itself, or an unrelated event.",
}


class JevError(RuntimeError):
    pass


def jev_ask(state, questions, key=None, model=JEV_MODEL, post=None, tries=4):
    """One System One call: {"model", "answers", "usage"}. Retries 429/529/5xx
    with backoff (the docs ask for it). `post(url, body, headers)` -> (status,
    bytes, error) is injectable; tests pass a fake client instead of this."""
    key = key or os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise JevError("no TYPESAFE_API_KEY set")
    post = post or (lambda url, body, headers: http_get(url, timeout=60, data=body,
                                                       headers=headers))
    body = json.dumps({"state": state, "model": model, "questions": questions}).encode()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    for attempt in range(tries):
        status, resp, err = post(JEV_URL, body, headers)
        if not err:
            return json.loads(resp)
        if status not in (429, 529, 500, 502, 503, 504, None) or attempt == tries - 1:
            raise JevError(f"jev call failed: {err}")
        time.sleep(2 ** attempt)


# ------------------------------------------------------------ full text

FULLTEXT_LOG = "fulltext.jsonl"   # article text stays in the state directory, never the repo
TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"


def extract_text(url, key=None, depth="advanced", post=None):
    """An article's text via Tavily extract: {"url", "text", "chars"} or, when
    it cannot be read, {"url", "text": "", "error"}. Raises only with no key.
    "advanced" depth costs 2 credits per 5 URLs (about a cent per article)."""
    key = key or os.environ.get("TAVILY_API_KEY")
    if not key:
        raise RuntimeError("no TAVILY_API_KEY set")
    post = post or (lambda url, body, headers: http_get(url, timeout=90, data=body, headers=headers))
    body = json.dumps({"urls": [url], "extract_depth": depth}).encode()
    status, resp, err = post(TAVILY_EXTRACT_URL, body,
                             {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    if err:
        return {"url": url, "text": "", "error": err}
    data = json.loads(resp)
    res = data.get("results") or []
    if not res:
        failed = data.get("failed_results") or [{}]
        return {"url": url, "text": "", "error": failed[0].get("error") or "no content returned"}
    text = res[0].get("raw_content") or ""
    return {"url": url, "text": text, "chars": len(text)}


def _prose(text, title=""):
    """The article's paragraphs of real prose, cleaned: no headline, byline,
    dateline-only or sign-up lines, links reduced to their text."""
    head = (title or "").lower()[:40]
    for para in re.split(r"\n+", text or ""):
        p = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", para)          # markdown links -> their text
        p = re.sub(r"[#*_>|]+", " ", re.sub("[\u200b-\u200d\u2060\ufeff]", "", p))
        p = re.sub(r"\s+", " ", p).strip()
        if len(p) < 80 or (head and head in p.lower()):
            continue
        if re.match(r"(by |reporting by|editing by|sign up|updated |share |\w+ \d+ \(reuters\) -$)", p.lower()):
            continue
        yield p


def lede(text, title=""):
    """The article's opening paragraph, as a standfirst for a report that came
    without one (Google News items): the first paragraph of real prose."""
    return next(_prose(text, title), "")[:SUMMARY_CHARS]


def opening(text, title="", words=250):
    """The article's first `words` words of prose, cut mid-sentence if need be
    ("…" marks a cut): the same length for every story, so that no story reads
    as weightier for having more text."""
    out = []
    for p in _prose(text, title):
        out += p.split()
        if len(out) >= words:
            return " ".join(out[:words]) + " …"
    return " ".join(out)


def fetch_fulltext(item_ids, items, state_dir=STATE_DIR, extract=extract_text, now=None):
    """Extract each item's article once and log it to fulltext.jsonl. Returns the rows."""
    have = {r["item"] for r in read_jsonl(os.path.join(state_dir, FULLTEXT_LOG)) if r.get("text")}
    rows = []
    for i in item_ids:
        if i in have:
            continue
        it = items[i]
        link = it.get("link") or ""
        # the publisher's own link: the canonical form drops "www.", which some sites refuse
        url = it["url"] if not link or "news.google.com" in link else link
        r = extract(url)
        if not r.get("text") and "://www." not in url:   # some sites answer only on www.
            r2 = extract(url.replace("://", "://www.", 1))
            r = r2 if r2.get("text") else r
        r = dict(r, item=i, at=now or _now())
        append_jsonl(os.path.join(state_dir, FULLTEXT_LOG), [r])
        rows.append(r)
    return rows


def first_readable(story, items):
    """The story's first report, in member order, whose article text was read; else None."""
    return next((items[m["item"]] for m in story["members"] if items[m["item"]].get("text")), None)


def fetch_first_readable(stories, items, state_dir=STATE_DIR, extract=extract_text, now=None):
    """For each story with no readable report yet, try its reports in member
    order until one's article is read. A report already tried is not tried
    again. Returns the rows logged."""
    tried = {r["item"] for r in read_jsonl(os.path.join(state_dir, FULLTEXT_LOG))}
    rows = []
    for s in stories:
        if first_readable(s, items):
            continue
        for m in s["members"]:
            if m["item"] in tried:
                continue
            r = fetch_fulltext([m["item"]], items, state_dir, extract, now)[0]
            tried.add(m["item"])
            rows.append(r)
            if r.get("text"):
                items[m["item"]]["text"] = r["text"]
                break
    return rows


def _ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def item_time(it):
    return it.get("published") or it["first_fetched"]


STOPWORDS = set("""a about after again against all also an and any are as at be been before
being but by can could did do does for from had has have he her his how i if in into is it
its just more most new no not now of on one or our out over says said she so some than that
the their them then there these they this those to too under up us was we were what when
where which who why will with would you your ai a.i artificial intelligence""".split())


def words(text):
    out = set()
    for w in re.findall(r"[a-z0-9][a-z0-9'.-]*", (text or "").lower()):
        w = w.strip(".'-")
        if w.endswith("'s"):
            w = w[:-2]
        if len(w) > 2 and w not in STOPWORDS:
            out.add(w[:-1] if len(w) > 4 and w.endswith("s") else w)
    return out


def item_view(it):
    """What Jev sees of an item: no URL, no ids, nothing the decision does not need."""
    v = {"source": it["source"], "published": item_time(it)[:10], "headline": it["title"]}
    if it.get("summary"):
        v["standfirst"] = it["summary"]
    return v


def story_view(story, items):
    ids = [m["item"] for m in story["members"]]
    shown = ids[:1] + ids[1:][-(STORY_REPORTS - 1):]
    return {"reports": [item_view(items[i]) for i in shown]}


def shortlist(item, stories, items):
    """[(story, overlap score)], best first, at most SHORTLIST: the stories
    whose span [first_seen, last_seen] comes within WINDOW_HOURS of the item
    and that share at least MIN_OVERLAP content words with it."""
    t = _ts(item_time(item))
    w = timedelta(hours=WINDOW_HOURS)
    mine = words(item["title"] + " " + item.get("summary", ""))
    out = []
    for s in stories:
        if not (_ts(s["first_seen"]) - w <= t <= _ts(s["last_seen"]) + w):
            continue
        theirs = s["_words"]
        shared = len(mine & theirs)
        if shared < MIN_OVERLAP:
            continue
        out.append((s, shared / ((len(mine) * len(theirs)) ** 0.5 or 1)))
    out.sort(key=lambda p: (-p[1], p[0]["id"]))
    return out[:SHORTLIST]


def match_questions(cands, items):
    qs = {}
    for k, (s, _) in enumerate(cands):
        view = story_view(s, items)
        qs[f"same_{k}"] = {"type": "noul", "criteria": SAME_CRITERIA,
                           "instructions": {"story": view, "question": SAME_Q}}
        qs[f"followup_{k}"] = {"type": "noul", "criteria": FOLLOWUP_CRITERIA,
                               "instructions": {"story": view, "question": FOLLOWUP_Q}}
    return qs


def _noul(answers, qid):
    a = answers.get(qid) or {}
    v = a.get("noul")
    return round(float(v), 4) if v is not None else None


def _new_story(it, via="seed"):
    return {"id": "s-" + it["id"], "title": it["title"],
            "first_seen": item_time(it), "last_seen": item_time(it),
            "members": [], "sources": [], "related": [],
            "screen": {c: None for c in CAUSES}, "_words": set()}


def _add_member(story, it, via, p_same=None):
    story["members"].append({
        "item": it["id"], "source": it["source"], "feeds": it["feeds"], "title": it["title"],
        "url": it["url"], "published": it.get("published"),
        "open_access": it.get("open_access", False), "via": via, "p_same": p_same})
    t = item_time(it)
    story["first_seen"] = min(story["first_seen"], t)
    story["last_seen"] = max(story["last_seen"], t)
    if it["source"] not in story["sources"]:
        story["sources"].append(it["source"])
    story["_words"] |= words(it["title"] + " " + it.get("summary", ""))


def fold(items, decisions, ask=None, log=None, now=None, ai_feeds=None):
    """Fold `items` ({id: item}) into stories. `decisions` is the decision log
    (rows as logged); `ask(state, questions)` -> Jev response is called for a
    decision the log cannot supply, and `log(row)` records it. With ask=None
    (replay) nothing is called. `ai_feeds` is the ids of the AI-only feeds
    (default: data/news_feeds.json). Returns (stories, dropped ids, stats)."""
    now = now or _now()
    if ai_feeds is None:
        ai_feeds = {f["id"] for f in load_feeds() if f.get("ai_only")}
    gates, matches = {}, {}
    for d in decisions:
        (gates if d["kind"] == "gate" else matches)[d["item"]] = d
    order = sorted(items.values(), key=lambda it: (it["first_fetched"], item_time(it), it["id"]))
    stories, by_id, dropped = [], {}, []
    stats = {"items": len(order), "calls": 0, "reused": 0, "asked_again": 0,
             "undecided": 0, "input_tokens": 0}

    def call(state, qs):
        r = ask(state, qs)
        stats["calls"] += 1
        stats["input_tokens"] += (r.get("usage") or {}).get("input_tokens", 0)
        return r

    for it in order:
        # 1. the AI gate, for items only a non-AI feed has carried
        if not (it.get("ai_only_feed") or ai_feeds & set(it["feeds"])):
            g = gates.get(it["id"])
            if g is None:
                if ask is None:
                    stats["undecided"] += 1
                    continue
                r = call({"item": item_view(it)}, {"about_ai": AI_Q})
                g = {"at": now, "kind": "gate", "item": it["id"], "title": it["title"],
                     "model": r.get("model"), "p_ai": _noul(r["answers"], "about_ai"),
                     "usage": r.get("usage"), "thresholds": THRESHOLDS}
                gates[it["id"]] = g
                log and log(g)
            if (g["p_ai"] or 0) < AI_AT:
                dropped.append(it["id"])
                continue

        # 2. the shortlist, in code
        cands = shortlist(it, stories, items)
        if not cands:
            s = _new_story(it)
            _add_member(s, it, "seed")
            stories.append(s)
            by_id[s["id"]] = s
            continue

        # 3. the match: reuse the logged call if the candidates are the same
        ids = [s["id"] for s, _ in cands]
        logged = matches.get(it["id"])
        probs = None
        if logged and [c["story"] for c in logged["candidates"]] == ids:
            probs = {c["story"]: c for c in logged["candidates"]}
            stats["reused"] += 1
        elif ask is not None:
            if logged:
                stats["asked_again"] += 1
            r = call({"new_item": item_view(it)}, match_questions(cands, items))
            row = {"at": now, "kind": "match", "item": it["id"], "title": it["title"],
                   "model": r.get("model"), "usage": r.get("usage"), "thresholds": THRESHOLDS,
                   "candidates": [{"story": s["id"], "story_title": s["title"],
                                   "overlap": round(sim, 4),
                                   "p_same": _noul(r["answers"], f"same_{k}"),
                                   "p_followup": _noul(r["answers"], f"followup_{k}")}
                                  for k, (s, sim) in enumerate(cands)]}
            matches[it["id"]] = row
            log and log(row)
            probs = {c["story"]: c for c in row["candidates"]}
        elif logged:
            # replay with a changed candidate set: decide from what was logged
            probs = {c["story"]: c for c in logged["candidates"] if c["story"] in by_id}
            stats["reused"] += 1
        else:
            stats["undecided"] += 1
            continue

        scored = [(probs[sid]["p_same"] or 0, sid) for sid in ids if sid in probs]
        best = max(scored, key=lambda p: p[0], default=(0, None))   # ties: shortlist order
        if best[1] is not None and best[0] >= SAME_AT:
            _add_member(by_id[best[1]], it, "jev", best[0])
            continue
        s = _new_story(it)
        _add_member(s, it, "seed")
        for sid in ids:
            c = probs.get(sid)
            if c and (c.get("p_followup") or 0) >= FOLLOWUP_AT:
                s["related"].append({"story": sid, "p_followup": c["p_followup"],
                                     "p_same": c["p_same"]})
        stories.append(s)
        by_id[s["id"]] = s

    for s in stories:
        del s["_words"]
    stats.update(stories=len(stories), dropped=len(dropped))
    return stories, dropped, stats


def run_reduce(state_dir=STATE_DIR, replay=False, ask=None, now=None):
    """Fold every item into stories, asking Jev only for what the log lacks
    (nothing with replay=True), and rewrite stories.json."""
    items = load_items(state_dir)
    log_path = os.path.join(state_dir, "decisions.jsonl")
    decisions = read_jsonl(log_path)
    if not replay and ask is None:
        if not os.environ.get("TYPESAFE_API_KEY"):
            raise JevError("no TYPESAFE_API_KEY set; `reduce --replay` needs none")
        ask = jev_ask
    stories, dropped, stats = fold(items, decisions, ask=None if replay else ask,
                                   log=lambda row: append_jsonl(log_path, [row]), now=now)
    stories.sort(key=lambda s: (s["last_seen"], s["id"]), reverse=True)
    out = {"built_at": now or _now(), "thresholds": THRESHOLDS, "stats": stats,
           "dropped": dropped, "stories": stories}
    os.makedirs(state_dir, exist_ok=True)
    tmp = os.path.join(state_dir, "stories.json.tmp")
    with open(tmp, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(state_dir, "stories.json"))
    return stats


# --------------------------------------------------------------- report

def _md(s):
    return (s or "").replace("|", "\\|").replace("\n", " ")


def report(state_dir=STATE_DIR, close_calls=10):
    """A markdown audit of the state: what came in, what came out, the closest
    merge calls, the follow-up candidates and any feed that failed. Reads the
    state only; it contains headlines, so it belongs outside the repo."""
    items = load_items(state_dir)
    fetches = read_jsonl(os.path.join(state_dir, "fetches.jsonl"))
    decisions = read_jsonl(os.path.join(state_dir, "decisions.jsonl"))
    built = json.load(open(os.path.join(state_dir, "stories.json"))) \
        if os.path.exists(os.path.join(state_dir, "stories.json")) else {"stories": [], "dropped": []}
    stories = built["stories"]
    L = ["# AIRO news stories: sample report", ""]
    polls = sorted({f["at"] for f in fetches})
    if polls:
        L.append(f"{len(polls)} polls, {polls[0]} to {polls[-1]}. Stories built {built.get('built_at')}, "
                 f"thresholds {json.dumps(built.get('thresholds'))}.")
    multi = [s for s in stories if len(s["members"]) > 1]
    L += ["", "## In and out", "",
          f"- items in: **{len(items)}**",
          f"- dropped by the AI gate: **{len(built['dropped'])}**",
          f"- stories out: **{len(stories)}**, of which **{len(multi)}** have more than one item "
          f"and **{sum(len(set(s['sources'])) > 1 for s in stories)}** more than one source",
          f"- Jev calls logged: {sum(d['kind'] == 'match' for d in decisions)} match, "
          f"{sum(d['kind'] == 'gate' for d in decisions)} gate; input tokens "
          f"{sum((d.get('usage') or {}).get('input_tokens', 0) for d in decisions):,}", ""]
    L += ["| feed | fetches | failed | items first seen here |", "|---|---|---|---|"]
    by_feed = {}
    for f in fetches:
        b = by_feed.setdefault(f["feed"], [0, 0])
        b[0] += 1
        b[1] += bool(f.get("error") or not f.get("entries"))
    for fid, (n, bad) in sorted(by_feed.items()):
        L.append(f"| {fid} | {n} | {bad} | {sum(it['feed'] == fid for it in items.values())} |")

    bad = [f for f in fetches if f.get("error") or not f.get("entries")]
    L += ["", "## Feeds that broke or were blocked", ""]
    if not bad:
        L.append("None: every fetch returned a parseable feed with entries.")
    for f in bad[:40]:
        L.append(f"- {f['at']} {f['feed']}: status {f.get('status')}, "
                 f"{f.get('error') or 'no entries'}")

    pairs = [(abs((c["p_same"] or 0) - SAME_AT), d, c) for d in decisions if d["kind"] == "match"
             for c in d["candidates"]]
    pairs.sort(key=lambda p: p[0])
    L += ["", f"## The {close_calls} closest merge calls", "",
          f"Item and candidate story, ordered by distance of p(same event) from {SAME_AT}.", "",
          "| p_same | p_followup | new item | candidate story |", "|---|---|---|---|"]
    for _, d, c in pairs[:close_calls]:
        it = items.get(d["item"], {})
        L.append(f"| {c['p_same']} | {c['p_followup']} | {_md(it.get('source'))}: {_md(d['title'])} "
                 f"| {_md(c['story_title'])} |")

    fu = [(c["p_followup"], d, c) for d in decisions if d["kind"] == "match"
          for c in d["candidates"] if (c.get("p_followup") or 0) >= FOLLOWUP_AT]
    fu.sort(key=lambda p: -p[0])
    L += ["", "## Follow-up candidates (for the follow-up policy)", "",
          f"Pairs Jev rated p(follow-up) >= {FOLLOWUP_AT}. Under the current rule a follow-up that is "
          "not the same event seeds its own story and is linked as related.", "",
          "| p_followup | p_same | new item | earlier story |", "|---|---|---|---|"]
    for _, d, c in fu[:25]:
        L.append(f"| {c['p_followup']} | {c['p_same']} | {_md(d['title'])} | {_md(c['story_title'])} |")

    gates = [d for d in decisions if d["kind"] == "gate"]
    L += ["", "## AI gate", "", "| p_ai | kept | item |", "|---|---|---|"]
    for d in sorted(gates, key=lambda d: d["p_ai"] or 0):
        L.append(f"| {d['p_ai']} | {'yes' if (d['p_ai'] or 0) >= AI_AT else 'no'} | {_md(d['title'])} |")

    L += ["", "## Stories with more than one item", ""]
    for s in multi:
        L.append(f"### {_md(s['title'])}")
        L.append(f"{s['first_seen']} to {s['last_seen']}; sources: {', '.join(s['sources'])}")
        L.append("")
        for m in s["members"]:
            p = "seed" if m["via"] == "seed" else f"p_same {m['p_same']}"
            oa = "open" if m["open_access"] else "paywalled"
            L.append(f"- [{p}] {m['source']} ({oa}): {_md(m['title'])} <{m['url']}>")
        for r in s["related"]:
            L.append(f"- related: {r['story']} (p_followup {r['p_followup']})")
        L.append("")

    L += ["## Single-item stories", "", "| last seen | source | headline |", "|---|---|---|"]
    for s in stories:
        if len(s["members"]) == 1:
            L.append(f"| {s['last_seen'][:16]} | {_md(s['sources'][0])} | {_md(s['title'])} |")
    return "\n".join(L) + "\n"
