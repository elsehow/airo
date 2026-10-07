"""redlines.autoreg: a model the index ranks into the panel gets a row with no hand step."""
import csv
import json
from datetime import date

import pytest

from redlines import autoreg, eci, registry


@pytest.mark.parametrize("name, ids, want", [
    ("GPT-6.1 Sol", ["gpt-6-sol", "gpt-6.1-sol", "gpt-6.1-sol-2026-09-29", "gpt-6.1-sol-mini"], "gpt-6.1-sol"),
    ("Claude Opus 5.5", ["claude-opus-5", "claude-opus-5-5", "claude-opus-5-5-20260922"], "claude-opus-5-5"),
    ("Claude Opus 5.5", ["claude-opus-5-5-20260922"], "claude-opus-5-5-20260922"),
    ("Gemini 3.1 Pro", ["gemini-3.1-pro-preview", "gemini-3.1-pro-preview-tts"], "gemini-3.1-pro-preview"),
    ("Grok 4.20", ["grok-4.20-0309-reasoning"], None),               # a suffix that is not a date
    ("Model 1", ["model-1-2025", "model-1-2026"], None),             # two equally good
    ("GPT-6 Sol", ["gpt-6.1-sol"], None),
])
def test_match_id(name, ids, want):
    assert autoreg.match_id(name, ids) == want


def test_family_matches_the_hand_rows():
    # The one-seat rule must hold across hand and automatic rows.
    by_epoch = {m["epoch_name"]: m["family"] for m in registry.MODELS if not m.get("auto")}
    for name in ["Claude Opus 5.5", "Claude Sonnet 5.5", "Claude Fable 5.1", "GPT-6 Astra",
                 "GPT-5.6 Sol", "GPT-5.5 Pro", "GPT-5.5", "Gemini 3.1 Pro", "Grok 4.20", "DeepSeek-V3"]:
        assert autoreg.family_for(name) == by_epoch[name], name
    assert autoreg.family_for("GPT-6.1 Sol") == "gpt-sol"


def test_label():
    assert autoreg.label_for("Claude Opus 5.5") == "Opus 5.5"
    assert autoreg.label_for("GPT-6.1 Sol") == "GPT-6.1 Sol"


def test_separation_is_the_validators_scale():
    # dataviz validate_palette.js on this pair: deutan 30.1, normal 32.2.
    assert 27 < autoreg.separation("#4f5bd5", "#5f8f1f") < 33
    assert autoreg.separation("#4f5bd5", "#4f5bd5") == 0


def test_pick_color_stands_apart_from_the_panel():
    panel = ["#4f5bd5", "#0e7c7b", "#d4892a", registry.RETIRED_COLOR]
    c = autoreg.pick_color(panel)
    assert c in autoreg.SPARE_COLORS
    worst = min(autoreg.separation(c, n) for n in panel)
    assert all(worst >= min(autoreg.separation(s, n) for n in panel) for s in autoreg.SPARE_COLORS)
    assert autoreg.pick_color(panel, taken=[c]) != c


def _snapshot(tmp_path, rows):
    path = tmp_path / "epoch_capabilities_index_2026-10-07.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Model", "Display name", "eci", "eci_ci_low", "eci_ci_high", "date",
                    "Organization", "Country (of organization)", "Model accessibility",
                    "Accessibility group", "model_versions"])
        for name, eci, org in rows:
            w.writerow([name, name, eci, eci - 3, eci + 4, "2026-09-29", org, "United States of America",
                        "API access", "Closed weights", ""])
    return date(2026, 10, 7), path


INDEX = [("Claude Opus 5.5", 167.33, "Anthropic"), ("GPT-6 Astra", 166.45, "OpenAI"),
         ("GPT-6.1 Sol", 166.09, "OpenAI"), ("Claude Sonnet 5.5", 165.03, "Anthropic"),
         ("Claude Fable 5.1", 164.7, "Anthropic")]


def test_resolve_adds_the_new_model(tmp_path):
    snap = _snapshot(tmp_path, INDEX)
    out = tmp_path / "auto_models.json"
    probed = []
    added, skipped = autoreg.resolve(snapshot=snap, path=out,
                                     lister=lambda p: ["gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol"],
                                     prober=lambda i: probed.append(i) or {"ok": True, "effort": "xhigh"})
    assert [m["epoch_name"] for m in added] == ["GPT-6.1 Sol"]
    m = added[0]
    assert m["litellm_id"] == "openai/responses/gpt-6.1-sol" and probed == [m["litellm_id"]]
    assert (m["key"], m["family"], m["label"], m["architecture"]) == \
        ("gpt-6.1-sol", "gpt-sol", "GPT-6.1 Sol", "undisclosed")
    assert m["color"] in autoreg.SPARE_COLORS
    assert json.loads(out.read_text()) == added
    # Recorded once: a second pass adds nothing and probes nothing.
    again, _ = autoreg.resolve(snapshot=snap, path=out, lister=lambda p: ["gpt-6.1-sol"],
                               prober=lambda i: pytest.fail("probed twice"))
    assert again == []


def test_a_failed_probe_takes_no_seat(tmp_path):
    snap = _snapshot(tmp_path, INDEX)
    out = tmp_path / "auto_models.json"
    added, skipped = autoreg.resolve(snapshot=snap, path=out, lister=lambda p: ["gpt-6.1-sol"],
                                     prober=lambda i: {"ok": False, "error": "BadRequestError"})
    assert added == [] and not out.exists()
    assert skipped and skipped[0][0] == "GPT-6.1 Sol" and "probe" in skipped[0][1]


def test_unmatched_and_unlistable_are_skipped(tmp_path):
    snap = _snapshot(tmp_path, INDEX[:2] + [("Mystery 1", 166.2, "Nobody Labs"), ("GPT-6.1 Sol", 166.09, "OpenAI")])
    out = tmp_path / "auto_models.json"

    def boom(p):
        raise OSError("network down")
    added, skipped = autoreg.resolve(snapshot=snap, path=out, lister=boom,
                                     prober=lambda i: pytest.fail("nothing to probe"))
    assert added == []
    assert {name for name, _ in skipped} == {"Mystery 1", "GPT-6.1 Sol"}


def test_registry_reads_the_record(tmp_path, monkeypatch):
    snap = _snapshot(tmp_path, INDEX)
    out = tmp_path / "auto_models.json"
    autoreg.resolve(snapshot=snap, path=out, lister=lambda p: ["gpt-6.1-sol"],
                    prober=lambda i: {"ok": True})
    real = registry.load_epoch_index

    def with_snapshot():
        idx = real()
        for name, rec in eci.load(snap[1]).items():
            idx.setdefault(name, rec)
        return idx
    monkeypatch.setattr(registry, "load_epoch_index", with_snapshot)
    auto = [m for m in registry._build_models(out) if m.get("auto")]
    assert [m["label"] for m in auto] == ["GPT-6.1 Sol"]
    assert auto[0]["eci"] == 166 and auto[0]["roles"] == []
    # A hand row for the same model wins.
    out.write_text(json.dumps([dict(json.loads(out.read_text())[0], epoch_name="GPT-6 Astra")]))
    assert not [m for m in registry._build_models(out) if m.get("auto")]
