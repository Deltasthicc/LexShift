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
