"""The model panel is the top-k of the newest ECI snapshot, and the ECI
snapshots have one reader.

  1. redlines.eci reads both snapshot formats, knows which is newest, and
     says when it is stale (> STALE_AFTER_DAYS) -- the WARN the project lead
     asked for on 2026-08-28, so a panel chosen on an old index announces itself.
  2. redlines.registry.panel() is the PANEL_K highest-ECI models the
     registry can run, re-ranked from that snapshot; an unrunnable model
     above the cut is skipped with a WARN, a tie at the cut is WARNed, and
     (2026-09-08) a second member of a family that already holds a seat is
     passed over with a WARN -- one seat per family.
  3. The pinned Graph-4 vintage is untouched by any of this, every row is
     drawable, and model_colors() still yields the frontier five in their
     original order once filtered to the models a view has rows for --
     which is why every tracked blob stayed byte-identical.

Run with:  python3 -m unittest tests.test_registry -v
"""
import csv
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from redlines import eci, registry  # noqa: E402


def _snapshot(tmp, day, rows):
    """Write a rank-format snapshot: rows are (model, eci)."""
    p = Path(tmp) / f"{eci.SNAPSHOT_PREFIX}{day}.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "model", "eci", "ci_low", "ci_high", "retrieved"])
        for i, (m, e) in enumerate(rows, 1):
            w.writerow([i, m, e, e - 3, e + 3, day])
    return date.fromisoformat(day), p


class TestSnapshots(unittest.TestCase):
    def test_both_formats_load_to_the_same_shape(self):
        rank = eci.load(eci.snapshot_path(date(2026, 8, 28)))
        raw = eci.load(REPO / "data" / "epoch_capabilities_index_2026-08-21.csv")
        published = eci.load(REPO / "data" / "epoch_capabilities_index_2026-10-01.csv")
        for rec in published.values():
            self.assertEqual({"model", "eci", "ci_low", "ci_high", "rank"} - set(rec), set())
        for idx in (rank, raw):
            for rec in idx.values():
                self.assertEqual({"model", "eci", "ci_low", "ci_high", "rank"} - set(rec), set())
        self.assertEqual(rank["Claude Fable 5"]["eci"], 162)
        self.assertEqual(rank["Claude Fable 5"]["ci_low"], 159)
        # The raw export: best variant per model name, no interval.
        self.assertAlmostEqual(raw["Claude Fable 5"]["eci"], 162.49)
        self.assertIsNone(raw["Claude Fable 5"]["ci_low"])
        self.assertEqual(raw["Claude Fable 5"]["rank"], 1)
        self.assertEqual(len(raw), 200)

    def test_latest_is_the_newest_by_filename_date_and_pinned_exists(self):
        snaps = eci.snapshots()
        self.assertEqual(snaps, sorted(snaps))
        self.assertEqual(eci.latest(), snaps[-1])
        self.assertTrue(eci.snapshot_path(eci.PINNED).exists())
        self.assertEqual(eci.PINNED, date(2026, 7, 7))       # Graph 4's vintage, unchanged

    def test_stale_after_a_month(self):
        day, path = eci.latest()
        self.assertIsNone(eci.stale_message(today=day))
        self.assertIsNone(eci.stale_message(today=day + timedelta(days=eci.STALE_AFTER_DAYS)))
        late = day + timedelta(days=eci.STALE_AFTER_DAYS + 1)
        msg = eci.stale_message(today=late)
        self.assertIn(path.name, msg)
        self.assertIn(f"{eci.STALE_AFTER_DAYS + 1} days old", msg)
        self.assertIn(eci.SNAPSHOT_URL, msg)
        buf = io.StringIO()
        self.assertEqual(eci.warn_if_stale(today=late, file=buf), msg)
        self.assertTrue(buf.getvalue().startswith("WARN: "))
        self.assertEqual(eci.STALE_AFTER_DAYS, 31)


PUBLISHED_HEADER = ["Model", "Display name", "eci", "eci_ci_low", "eci_ci_high", "date",
                    "Organization", "Country (of organization)", "Model accessibility",
                    "Accessibility group", "model_versions"]
US = "United States of America"


def _published_csv(rows):
    """Epoch's published format: rows are (model, eci, date, country)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(PUBLISHED_HEADER)
    for m, e, d, c in rows:
        w.writerow([m, m, e, e - 3 if e != "" else "", e + 3 if e != "" else "", d, "Lab", c, "API access", "Closed", ""])
    return buf.getvalue()


class TestPublishedFormat(unittest.TestCase):
    """Since 2026-10-01 the snapshot is Epoch's published CSV, fetched by the
    cron before every run (redlines.eci.fetch)."""

    def test_published_format_loads_to_the_same_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.csv"
            p.write_text(_published_csv([("A", 160.5, "2026-01-01", US), ("B", 161.25, "2026-02-01", "China"),
                                         ("C", "", "2026-03-01", US)]))
            idx = eci.load(p)
        self.assertEqual(set(idx), {"A", "B"})                  # unscored rows are skipped
        self.assertEqual({"model", "eci", "ci_low", "ci_high", "rank"} - set(idx["A"]), set())
        self.assertEqual((idx["B"]["rank"], idx["A"]["rank"]), (1, 2))
        self.assertEqual(idx["A"]["ci_low"], 157.5)
        self.assertEqual(idx["B"]["country"], "China")

    def test_frontier_is_us_new_highs_in_release_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.csv"
            p.write_text(_published_csv([
                ("Old", 150, "2022-01-01", US),        # before `since`: raises the bar, not listed
                ("Below", 149, "2023-05-01", US),
                ("First", 151, "2023-06-01", US),
                ("Foreign", 170, "2023-07-01", "China"),
                ("SameDayLow", 152, "2024-01-01", US),
                ("SameDayHigh", 153, "2024-01-01", US),
                ("Later", 152.5, "2024-02-01", US),
            ]))
            hist = eci.frontier_history(p, since="2023-03-01")
        self.assertEqual([m for _, _, m in hist], ["First", "SameDayLow", "SameDayHigh"])

    def test_fetch_writes_today_and_refuses_a_bad_download(self):
        good = _published_csv([(f"M{i}", 100 + i, "2025-01-01", US) for i in range(eci.MIN_SCORED)])

        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        import urllib.request
        real = urllib.request.urlopen
        with tempfile.TemporaryDirectory() as tmp:
            old_dir = eci.SNAPSHOT_DIR
            eci.SNAPSHOT_DIR = Path(tmp)
            try:
                urllib.request.urlopen = lambda *a, **k: Resp(good.encode())
                path = eci.fetch(today=date(2026, 10, 1))
                self.assertEqual(path.name, "epoch_capabilities_index_2026-10-01.csv")
                self.assertEqual(eci.latest_published()[1], path)
                for bad in (good.splitlines()[0] + "\n" + "\n".join(good.splitlines()[1:10]),
                            "Model,eci\nA,1\n"):
                    urllib.request.urlopen = lambda *a, **k: Resp(bad.encode())
                    with self.assertRaises(ValueError):
                        eci.fetch(today=date(2026, 10, 2))
                self.assertEqual([d for d, _ in eci.snapshots()], [date(2026, 10, 1)])
            finally:
                urllib.request.urlopen = real
                eci.SNAPSHOT_DIR = old_dir


class TestPanel(unittest.TestCase):
    def test_panel_is_the_top_k_runnable_models_of_the_latest_snapshot(self):
        members = registry.panel()
        self.assertEqual(len(members), registry.PANEL_K)
        self.assertEqual(registry.PANEL_K, 4)
        by_epoch = {m["epoch_name"]: m for m in registry.MODELS}
        want, seated = [], set()
        for r in eci.ranked():
            m = by_epoch.get(r["model"])
            if m is None or m["family"] in seated:
                continue
            want.append(r["model"]); seated.add(m["family"])
            if len(want) == registry.PANEL_K:
                break
        self.assertEqual([m["epoch_name"] for m, _ in members], want)
        ecis = [r["eci"] for _, r in members]
        self.assertEqual(ecis, sorted(ecis, reverse=True))
        # On the 2026-08-28 snapshot, the ECI top-4 arm (docs/eci-top4-arm.md).
        if eci.latest()[0] == date(2026, 8, 28):
            self.assertEqual([m["label"] for m, _ in members],
                             ["Fable 5", "GPT-5.5 Pro", "Opus 5", "GPT-5.6 Sol"])
        # On the 2026-09-08 snapshot (the project lead's pick): Fable 5 passed
        # over for Fable 5.1, GPT-5.5 Pro over GPT-5.6 Sol on the tie.
        if eci.latest()[0] == date(2026, 9, 8):
            self.assertEqual([m["label"] for m, _ in members],
                             ["GPT-6 Astra", "Fable 5.1", "Opus 5", "GPT-5.5 Pro"])
            warns = registry.panel_warnings()
            self.assertTrue(any("passed over Claude Fable 5 (163)" in w and "Claude Fable 5.1" in w for w in warns), warns)
            self.assertTrue(any("tie at the cut: GPT-5.5 Pro" in w and "GPT-5.6 Sol" in w for w in warns), warns)
        # The staleness WARN is part of the panel's warnings exactly when the
        # snapshot is stale today -- no more, no less.
        warns = registry.panel_warnings()
        stale = eci.stale_message()
        self.assertEqual(any("days old" in w for w in warns), stale is not None)

    def test_unrunnable_models_are_skipped_with_a_warning_and_ties_are_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = _snapshot(tmp, "2026-09-04", [
                ("Kimi K3", 170),               # not in the registry: skipped, named
                ("Claude Fable 5", 165),
                ("GPT-5.5 Pro", 164),
                ("Claude Opus 5", 163),
                ("GPT-5.6 Terra", 162),         # not in the registry, above the cut
                ("GPT-5.6 Sol", 161),
                ("GPT-5.5", 161),               # tied with the cut, out on rank
                ("Claude Opus 4.8", 158),
            ])
            buf = io.StringIO()
            with redirect_stderr(buf):
                members = registry.panel(snapshot=snap)
            warns = registry.panel_warnings(snapshot=snap)
        self.assertEqual([m["label"] for m, _ in members], ["Fable 5", "GPT-5.5 Pro", "Opus 5", "GPT-5.6 Sol"])
        self.assertTrue(any("Kimi K3" in w and "GPT-5.6 Terra" in w and "cannot run" in w for w in warns), warns)
        self.assertTrue(any("tie at the cut" in w and "GPT-5.5" in w for w in warns), warns)
        for w in warns:
            self.assertIn(f"WARN: {w}", buf.getvalue())

    def test_one_seat_per_family(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = _snapshot(tmp, "2026-09-06", [
                ("Claude Fable 5.1", 170),
                ("Claude Fable 5", 169),        # same family as the seat above: passed over
                ("Claude Opus 5", 165),
                ("Claude Opus 4.8", 164),       # ditto
                ("GPT-5.5 Pro", 163),
                ("GPT-5.6 Sol", 162),           # takes the fourth seat
                ("GPT-5.5", 160),
            ])
            with redirect_stderr(io.StringIO()):
                members = registry.panel(snapshot=snap)
            warns = registry.panel_warnings(snapshot=snap)
        self.assertEqual([m["label"] for m, _ in members], ["Fable 5.1", "Opus 5", "GPT-5.5 Pro", "GPT-5.6 Sol"])
        self.assertTrue(any("passed over Claude Fable 5 (169)" in w and "claude-fable" in w and "Claude Fable 5.1" in w for w in warns), warns)
        self.assertTrue(any("passed over Claude Opus 4.8 (164)" in w for w in warns), warns)
        self.assertEqual(len({m["family"] for m, _ in members}), len(members))
        for m in registry.MODELS:
            self.assertTrue(m["family"], m["key"])

    def test_a_short_snapshot_gives_a_short_panel_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            snap = _snapshot(tmp, "2026-09-05", [("Claude Fable 5", 165), ("Nobody", 160)])
            with redirect_stderr(io.StringIO()):
                members = registry.panel(snapshot=snap)
            warns = registry.panel_warnings(snapshot=snap)
        self.assertEqual([m["label"] for m, _ in members], ["Fable 5"])
        self.assertTrue(any("panel is short" in w for w in warns), warns)

    def test_the_sets_and_the_default(self):
        self.assertEqual(registry.DEFAULT_MODEL_SET, registry.PANEL_SET)
        self.assertEqual(set(registry.MODEL_SETS), {"eci_topk", "frontier5"})
        self.assertEqual(registry.MODEL_SETS["eci_topk"](),
                         [(m["label"], m["litellm_id"]) for m, _ in registry.panel()])
        self.assertEqual([l for l, _ in registry.frontier_models()],
                         ["Fable 5", "GPT-5.5", "Opus 4.8", "Gemini 3.1 Pro", "Grok 4.20"])
        prov = registry.panel_provenance()
        self.assertEqual({"set", "k", "snapshot", "age_days", "members"}, set(prov))
        self.assertEqual(prov["snapshot"], eci.latest()[0].isoformat())
        self.assertEqual(len(prov["members"]), registry.PANEL_K)
        self.assertEqual(registry.panel_provenance("frontier5"), {"set": "frontier5"})

    def test_runner_defaults_to_the_panel_and_stamps_it(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("run_unified", REPO / "code" / "run_unified.py")
        ru = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ru)
        self.assertEqual(ru.DEFAULT_MODEL_SET, "eci_topk")
        args = SimpleNamespace(model_set="eci_topk", models=None, smoke=False)
        with redirect_stderr(io.StringIO()):
            import contextlib
            with contextlib.redirect_stdout(io.StringIO()) as out:
                models, stamp = ru.select_models(args)
        self.assertEqual(len(models), registry.PANEL_K)
        self.assertEqual(stamp, {"set": "eci_topk", "k": registry.PANEL_K,
                                 "snapshot": eci.latest()[0].isoformat()})
        self.assertIn("panel eci_topk: top 4 by ECI, snapshot", out.getvalue())
        args = SimpleNamespace(model_set="frontier5", models="fable 5", smoke=False)
        with contextlib.redirect_stdout(io.StringIO()):
            models, stamp = ru.select_models(args)
        self.assertEqual(models, [("Fable 5", "anthropic/claude-fable-5")])
        self.assertEqual(stamp, {"set": "frontier5"})


class TestPublishedPanel(unittest.TestCase):
    def test_the_views_panel_is_the_one_the_rows_were_chosen_as(self):
        """A fetched snapshot moves panel() at once; the views follow the
        snapshot stamped on the newest rows, so they neither blank nor recolor
        before the first run on the new panel lands."""
        old = [{"panel": {"set": "eci_topk", "k": 4, "snapshot": "2026-09-08"},
                "run_date": "2026-09-18", "elicited_at": "2026-09-18T12:00:00Z"}]
        new = old + [{"panel": {"set": "eci_topk", "k": 4, "snapshot": "2026-10-01"},
                      "run_date": "2026-10-02", "elicited_at": "2026-10-02T12:00:00Z"}]
        with redirect_stderr(io.StringIO()):
            self.assertEqual([m["label"] for m, _ in registry.published_panel(rows=old)],
                             ["GPT-6 Astra", "Fable 5.1", "Opus 5", "GPT-5.5 Pro"])
            self.assertEqual([m["label"] for m, _ in registry.published_panel(rows=new)],
                             [m["label"] for m, _ in registry.panel(snapshot=(date(2026, 10, 1),
                              eci.snapshot_path(date(2026, 10, 1))))])
        self.assertIsNone(registry.snapshot_of([{"panel": {"set": "frontier5"}}]))
        self.assertIsNone(registry.snapshot_of([{"panel": {"snapshot": "1999-01-01"}}]))   # file not in data/


class TestTableInvariants(unittest.TestCase):
    def test_pinned_vintage_and_colors(self):
        by = {m["key"]: m for m in registry.MODELS}
        self.assertEqual(by["claude-fable-5"]["eci"], 161)        # pinned 2026-07-07, not 162
        self.assertEqual(by["gpt-5.5"]["eci"], 159)
        self.assertEqual(by["claude-opus-5"]["eci"], 163)          # predates the pin: from eci.SUPPLEMENT (2026-09-08)
        self.assertEqual(by["gpt-5.6-sol"]["eci"], 162)
        self.assertEqual(by["claude-fable-5-1"]["eci"], 164)      # 2026-09-08 snapshot
        self.assertEqual(by["gpt-6-astra"]["eci"], 167)
        self.assertEqual(by["gpt-6-astra"]["litellm_id"], "openai/responses/gpt-6-astra")
        # 2026-10-01: newer than both files, so from the newest snapshot.
        self.assertEqual(by["claude-opus-5-5"]["eci"], 167)
        self.assertEqual(by["claude-sonnet-5-5"]["eci"], 165)
        for m in registry.MODELS:
            self.assertRegex(m["color"], r"^#[0-9a-f]{6}$", m["key"])
        self.assertEqual(len({m["color"] for m in registry.MODELS}), len(registry.MODELS))

    def test_model_colors_is_panel_in_its_colors_then_everyone_in_gray(self):
        mc = registry.model_colors()
        labels = [l for l, _ in mc]
        # The dashboard colors the panel the newest run was chosen as, not
        # the one the next run will be (2026-10-01: the index is fetched
        # before every run, so the two differ until that run lands).
        panel = [m for m, _ in registry.published_panel()]
        self.assertEqual(labels[:registry.PANEL_K], [m["label"] for m in panel])
        self.assertEqual(len(mc), len(registry.MODELS))
        frontier = [l for l, _ in registry.frontier_models()]
        self.assertEqual([l for l in labels if l in frontier], frontier)
        colors = dict(mc)
        # Panel members in their registry colors; everyone else in the one gray.
        for m in panel:
            self.assertEqual(colors[m["label"]], m["color"])
            self.assertEqual(registry.color_for(m), m["color"])
        members = {m["key"] for m in panel}
        for m in registry.MODELS:
            if m["key"] not in members:
                self.assertEqual(colors[m["label"]], registry.RETIRED_COLOR, m["key"])
                self.assertEqual(registry.color_for(m), registry.RETIRED_COLOR)
        self.assertNotIn(registry.RETIRED_COLOR, {m["color"] for m in registry.MODELS})


if __name__ == "__main__":
    unittest.main()
