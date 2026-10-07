from m3_treatment.citations import find_cites
from m3_treatment.resolver import CorpusIndex, bench_of


def rec(doc_id, title, date, cites=(), bench=None, judges=()):
    return {"doc_id": doc_id, "title": title, "date": date, "bench_size": bench, "judges": list(judges), "reporter_citations": list(cites)}


CORPUS = [
    rec("2013_17_116_200", "SURESH KUMAR KOUSHAL & ANR. versus NAZ FOUNDATION & ORS.", "2013-12-11", ["[2013] 17 S.C.R. 116"], 2),
    rec("2018_7_379_746", "NAVTEJ SINGH JOHAR & ORS. versus UNION OF INDIA", "2018-09-06", ["[2018] 7 S.C.R. 379", "2018 INSC 790"], 5),
    rec("1980_2_1_50", "BACHAN SINGH versus STATE OF PUNJAB", "1980-05-09", [], None, ["A", "B", "C", "D", "E"]),
    rec("2010_2_633_640", "MULLA versus STATE OF UTTAR PRADESH", "2010-02-08"),
    rec("2010_3_1_10", "RAM SINGH versus STATE OF HARYANA", "2010-03-01"),
    rec("2010_3_11_20", "RAM SINGH versus STATE OF HARYANA", "2010-04-01"),
]


def idx(**kw):
    return CorpusIndex(CORPUS, min_stop_df=3, max_token_df=0.3, **kw)


def test_exact_reporter_key_and_neutral_citation():
    i = idx()
    assert i.resolve_cites(find_cites("[2013] 17 SCR 116")).doc_id == "2013_17_116_200"
    assert i.resolve_cites(find_cites("2018 INSC 790")).doc_id == "2018_7_379_746"
    r = i.resolve_cites(find_cites("(2014) 1 SCC 1 : [2013] 17 SCR 116"))
    assert (r.doc_id, r.method) == ("2013_17_116_200", "cite")


def test_scr_pinpoint_page_falls_inside_the_report_range():
    r = idx().resolve_cites(find_cites("[2018] 7 SCR 450"))
    assert (r.doc_id, r.method) == ("2018_7_379_746", "scr_range")
    assert idx().resolve_cites(find_cites("[2018] 7 SCR 900")).doc_id is None


def test_name_fallback_uses_jaccard_and_year():
    i = idx()
    r = i.resolve([c for c in find_cites("(2014) 1 SCC 1")], "Suresh Kumar Koushal and Anr. v. Naz Foundation and Ors.", 2014)
    assert r.doc_id == "2013_17_116_200" and r.method == "name"
    # same name, wrong year: refused
    assert i.resolve_name("Suresh Kumar Koushal v. Naz Foundation", 1990).doc_id is None
    # no year: stricter threshold, still fine for a full name
    assert i.resolve_name("Bachan Singh v. State of Punjab").doc_id == "1980_2_1_50"


def test_ambiguous_names_are_left_unresolved():
    r = idx().resolve_name("Ram Singh v. State of Haryana", 2010)
    assert r.doc_id is None and r.method == "none"


def test_corpus_driven_stop_words():
    i = idx()
    assert "state" in i.stopwords and "koushal" not in i.stopwords


def test_bench_falls_back_to_listed_judges_never_guessed():
    assert bench_of({"bench_size": 3, "judges": []}) == 3
    assert bench_of({"bench_size": None, "judges": ["A", "B"]}) == 2
    assert bench_of({"bench_size": None, "judges": []}) is None
    assert idx().meta["1980_2_1_50"].bench == 5


def test_a_lone_rare_word_or_shared_common_words_cannot_carry_a_match():
    corpus = CORPUS + [rec("2013_1_1_9", "SUSHIL SHARMA versus THE STATE OF N.C.T. OF DELHI", "2013-01-01")]
    i = CorpusIndex(corpus, min_stop_df=3, max_token_df=0.3)
    assert i.resolve_name("Sushil Kumar v. State of Punjab").doc_id is None
    assert i.resolve_name("Ram Kumar v. State of Haryana", 2010).doc_id is None


def test_page_range_match_is_rejected_when_the_name_disagrees():
    i = idx()
    cites = find_cites("[2018] 7 SCR 450")
    assert i.resolve(cites, "Navtej Singh Johar v. Union of India", 2018).doc_id == "2018_7_379_746"
    # a misprinted page landing in someone else's report: the name wins
    assert i.resolve(cites, "Suresh Kumar Koushal v. Naz Foundation", 2013).doc_id == "2013_17_116_200"


def test_bare_cite_needs_an_exact_first_page():
    i = idx()
    assert i.resolve(find_cites("[2013] 17 SCR 116")).doc_id == "2013_17_116_200"
    assert i.resolve(find_cites("[2013] 17 SCR 150")).doc_id is None  # in range, but nothing to check it against


def test_bench_from_the_coram_line():
    from m3_treatment.resolver import bench_from_text

    assert bench_from_text("STATE OF KERALA\n[MADAN B. LOKUR, S. ABDUL NAZEER AND\nDEEPAK GUPTA, JJ.]\nPractice") == 3
    five = "[DIPAK MISRA, CJI ]\n[DIPAK MISRA, CJI, R. F. NARIMAN, A. M. KHANWILKAR, DR. D.Y. CHANDRACHUD AND INDU MALHOTRA, JJ.]"
    assert bench_from_text(five) == 5
    assert bench_from_text("[for himself and Khanwilkar, J.] [Paras 15, 16]") is None
    assert bench_of({"bench_size": None, "judges": ["R. BANUMATHI"], "text": "[R. BANUMATHI AND INDIRA BANERJEE, JJ.]"}) == 2
    assert bench_of({"bench_size": None, "judges": ["G.S. SINGHVI"], "text": ""}) is None  # one name may be just the author


def test_data_checks_flag_missing_m1_fields():
    levels = lambda checks: [lvl for lvl, _ in checks]  # noqa: E731
    good = CorpusIndex([rec("2013_17_116_200", "A v. B", "2013-01-01", ["[2013] 17 S.C.R. 116"], 2)])
    assert levels(good.data_checks()) == ["OK", "OK", "OK"]
    # M1 shipped no bench, no reporter citations and its own ids: every dependency is reported
    bad = CorpusIndex([rec("J1", "A v. B", "2013-01-01"), rec("J2", "C v. D", "2014-01-01")])
    assert levels(bad.data_checks()) == ["ERROR", "WARN", "WARN"]
    assert "bench" in bad.data_checks()[0][1] and "never" in bad.data_checks()[0][1]
    half = CorpusIndex([rec("2013_1_1_9", "A v. B", "2013-01-01", bench=2), rec("2013_1_10_19", "C v. D", "2013-01-01"), rec("2013_1_20_29", "E v. F", "2013-01-01")])
    assert half.data_checks()[0][0] == "WARN"


def test_the_coram_line_wins_over_a_stored_bench_size():
    """M1 stored 7 three-judge benches as 2 ("Vikram Nath, Sanjay Karol" kept as one name); the coram line is right."""
    from m3_treatment.resolver import bench_of

    text = "Some headnote.\n[Vikram Nath, Sanjay Karol and Sandeep Mehta,* JJ.]\nJudgment follows."
    assert bench_of({"bench_size": 2, "judges": ["Vikram Nath, Sanjay Karol", "Sandeep Mehta"], "text": text}) == 3
    assert bench_of({"bench_size": 2, "judges": [], "text": "no coram line here"}) == 2
    assert bench_of({"bench_size": None, "judges": ["A", "B", "C"], "text": ""}) == 3
    assert bench_of({"bench_size": None, "judges": ["Author only"], "text": ""}) is None
