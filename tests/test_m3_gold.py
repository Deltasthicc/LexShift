import csv

import pytest

from common.schema import GoldWindow, SchemaError
from m3_treatment.gold import cohens_kappa, cue_bucket, final_labels, load_gold, merge, sample_candidate_windows, write_sheets


def test_kappa_matches_sklearn_and_textbook_cases():
    from sklearn.metrics import cohen_kappa_score

    a = ["neutral", "neutral", "followed", "overruled", "followed", "neutral", "doubted", "neutral"]
    b = ["neutral", "followed", "followed", "overruled", "followed", "neutral", "neutral", "neutral"]
    assert cohens_kappa(a, b) == pytest.approx(cohen_kappa_score(a, b))
    assert cohens_kappa(a, a) == 1.0
    with pytest.raises(ValueError):
        cohens_kappa([], [])


def test_cue_bucket_only_looks_near_the_target():
    assert cue_bucket("We hold that [[Koushal (supra)]] is overruled.") == "overrule"
    assert cue_bucket("[[A v. B]] was cited." + " x" * 200 + " the objection is overruled.") == "none"


def mention(i, window, appeal=False):
    return {"citing_doc": f"D{i}", "start": i, "end": i + 5, "marked_window": window, "cited_doc": None, "cited_raw": "X", "kind": "full", "is_appeal_history": appeal}


def test_sampler_balances_buckets_skips_appeal_history_and_duplicates():
    ms = [mention(i, f"[[X{i}]] was referred to.") for i in range(50)]
    ms += [mention(100 + i, f"[[Y{i}]] is overruled.") for i in range(3)]
    ms += [mention(200, "[[Z]] is overruled.", appeal=True), mention(201, "[[X0]] was referred to.")]
    out = sample_candidate_windows(10, seed=1, mentions=ms)
    assert len(out) == 10
    assert sum(r["bucket"] == "overrule" for r in out) == 3  # every rare candidate is kept
    assert all(not r["is_appeal_history"] for r in out)
    assert len({r["marked_window"] for r in out}) == 10
    assert out == sample_candidate_windows(10, seed=1, mentions=ms)  # deterministic


def fill(path, labels):
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    for r in rows:
        r["gold_label"] = labels.get(r["window_id"], "")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def test_full_labelling_round(tmp_path):
    ms = [mention(i, f"[[C{i}]] text {i}.") for i in range(6)]
    cands = sample_candidate_windows(6, seed=0, mentions=ms)
    paths = write_sheets(cands, tmp_path, double=3)
    with pytest.raises(FileExistsError):
        write_sheets(cands, tmp_path, double=3)  # a round is never overwritten
    ids = [c["window_id"] for c in cands]
    l2_ids = [r["window_id"] for r in csv.DictReader(open(paths["L2"], encoding="utf-8"))]
    fill(paths["L1"], {i: "neutral" for i in ids})
    fill(paths["L2"], {i: ("followed" if n == 0 else "neutral") for n, i in enumerate(l2_ids)})
    gold = tmp_path / "gold.csv"
    rep = merge(tmp_path, gold)
    assert rep["double"] == 3 and rep["disagreements"] == 1 and rep["unadjudicated"] == 1
    rows = load_gold(gold)
    assert len(final_labels(rows)) == 5  # the unadjudicated disagreement is left out
    # adjudicate it and merge again
    dis = tmp_path / "disagreements.csv"
    drows = list(csv.DictReader(open(dis, encoding="utf-8")))
    drows[0]["adjudicated"] = "followed"
    with open(dis, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(drows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(drows)
    rep = merge(tmp_path, gold)
    assert rep["unadjudicated"] == 0
    labels = dict(final_labels(load_gold(gold)))
    assert len(labels) == 6 and list(labels.values()).count("followed") == 1


def test_bad_label_in_a_sheet_is_rejected(tmp_path):
    ms = [mention(i, f"[[C{i}]] text.") for i in range(2)]
    paths = write_sheets(sample_candidate_windows(2, mentions=ms), tmp_path, double=0)
    fill(paths["L1"], {r["window_id"]: "bad law" for r in csv.DictReader(open(paths["L1"], encoding="utf-8"))})
    with pytest.raises(SchemaError):
        merge(tmp_path, tmp_path / "g.csv")


def test_final_labels_prefers_adjudication():
    rows = [GoldWindow("w1", "[[A]]", "neutral", "L1"), GoldWindow("w1", "[[A]]", "followed", "L2"), GoldWindow("w1", "[[A]]", "followed", "ADJ")]
    assert final_labels(rows) == [("[[A]]", "followed")]


def _round(tmp_path, n=6, double=3):
    ms = [mention(i, f"[[C{i}]] text {i}.") for i in range(n)]
    cands = sample_candidate_windows(n, seed=0, mentions=ms)
    paths = write_sheets(cands, tmp_path, double=double)
    l2_ids = [r["window_id"] for r in csv.DictReader(open(paths["L2"], encoding="utf-8"))]
    return paths, [c["window_id"] for c in cands], l2_ids


def _adjudicate_all(tmp_path, label="followed"):
    dis = tmp_path / "disagreements.csv"
    rows = list(csv.DictReader(open(dis, encoding="utf-8")))
    for r in rows:
        r["adjudicated"] = label
    with open(dis, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["window_id", "window", "L1", "L2", "adjudicated"], lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return dis.read_text(encoding="utf-8")


def test_missing_second_sheet_is_refused_and_adjudications_survive(tmp_path):
    from m3_treatment.gold import MergeError

    paths, ids, l2 = _round(tmp_path)
    fill(paths["L1"], {i: "neutral" for i in ids})
    fill(paths["L2"], {i: "followed" for i in l2})
    merge(tmp_path, tmp_path / "gold.csv")
    typed = _adjudicate_all(tmp_path)
    paths["L2"].unlink()
    with pytest.raises(MergeError, match="missing"):
        merge(tmp_path, tmp_path / "gold.csv")
    assert (tmp_path / "disagreements.csv").read_text(encoding="utf-8") == typed  # untouched


def test_merge_never_drops_a_typed_adjudication(tmp_path):
    from m3_treatment.gold import MergeError

    paths, ids, l2 = _round(tmp_path)
    fill(paths["L1"], {i: "neutral" for i in ids})
    fill(paths["L2"], {i: "followed" for i in l2})
    merge(tmp_path, tmp_path / "gold.csv")
    typed = _adjudicate_all(tmp_path)
    fill(paths["L2"], {i: "neutral" for i in l2})  # the second labeller changed their sheet: no disagreement left
    with pytest.raises(MergeError, match="typed adjudication"):
        merge(tmp_path, tmp_path / "gold.csv")
    assert (tmp_path / "disagreements.csv").read_text(encoding="utf-8") == typed


def test_incomplete_sheets_are_refused_unless_allowed(tmp_path):
    from m3_treatment.gold import MergeError

    paths, ids, l2 = _round(tmp_path, n=8, double=2)
    fill(paths["L1"], {ids[0]: "neutral"})  # 7 of 8 blank
    fill(paths["L2"], {i: "neutral" for i in l2})
    gold = tmp_path / "gold.csv"
    with pytest.raises(MergeError, match="L1: 7 of 8 windows blank"):
        merge(tmp_path, gold)
    assert not gold.exists()
    rep = merge(tmp_path, gold, allow_incomplete=True)
    assert rep["blank_L1"] == 7 and rep["L1"] == 1


def test_swapped_sheets_are_refused(tmp_path):
    from m3_treatment.gold import MergeError

    paths, ids, l2 = _round(tmp_path)
    paths["L1"].rename(tmp_path / "x.csv")
    paths["L2"].rename(paths["L1"])
    (tmp_path / "x.csv").rename(paths["L2"])
    with pytest.raises(MergeError):
        merge(tmp_path, tmp_path / "gold.csv")
