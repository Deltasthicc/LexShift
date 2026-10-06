from m3_treatment.text import clean_text, jaccard, party_tokens, sentence_spans, split_parties
from m3_treatment.windows import citation_window, is_appeal_history, same_parties, window_span


def sentences(text):
    return [text[s:e].strip() for s, e in sentence_spans(text)]


def test_clean_text_drops_margin_letters_and_page_numbers_and_joins_lines():
    raw = "A\nB\n296\nThe two-Judge bench in Suresh\nKumar Koushal (supra) held that same-\nsex acts\nH\n"
    assert clean_text(raw) == "The two-Judge bench in Suresh Kumar Koushal (supra) held that same-sex acts"


def test_sentence_splitter_protects_legal_abbreviations_and_initials():
    text = (
        "In M. A. Antony v. State of Kerala, (2018) 13 SCR 296, the Court relied on S. 302 I.P.C. in that case. "
        "The appeal is allowed. 96. For all these reasons Koushal (supra) is overruled. Next sentence here."
    )
    out = sentences(text)
    assert out[0].startswith("In M. A. Antony v. State of Kerala") and out[0].endswith("in that case.")
    assert out[1] == "The appeal is allowed."
    assert out[2] == "96. For all these reasons Koushal (supra) is overruled."
    assert out[3] == "Next sentence here."


def test_ors_never_ends_a_sentence_known_limitation():
    # "Naz Foundation & Ors. (2014) 1 SCC 1" is far more common than a sentence ending in "Ors.", so the splitter
    # merges the rare true boundary; the cost is a slightly longer window, never a lost citation.
    assert len(sentences("Naz Foundation & Ors. The appeal is allowed.")) == 1


def test_sentence_splitter_keeps_cr_p_c_and_no_inside_a_sentence():
    out = sentences("Review Petition (Crl.) No. 245 of 2010 under Section 482 Cr.P.C. was dismissed. Then it went on.")
    assert out == ["Review Petition (Crl.) No. 245 of 2010 under Section 482 Cr.P.C. was dismissed.", "Then it went on."]


def test_window_is_citing_sentence_plus_neighbours():
    text = "One here. Two here. Koushal (supra) is overruled. Four here. Five here."
    start = text.index("Koushal")
    end = start + len("Koushal (supra)")
    assert citation_window(text, start, end, 1, 1) == "Two here. Koushal (supra) is overruled. Four here."
    assert citation_window(text, start, end, 0, 0) == "Koushal (supra) is overruled."
    assert citation_window(text, start, end, 2, 2) == text


def test_window_cap_drops_neighbours_then_centres_on_the_mention():
    long_sentence = "x " * 400 + "Bachan Singh v. State of Punjab (1980) 2 SCC 684 " + "y " * 400 + "end."
    text = "Before here. " + long_sentence + " After here."
    start = text.index("Bachan")
    lo, hi = window_span(text, start, start + 20, 1, 1, max_chars=300)
    assert hi - lo <= 300 and lo <= start < hi


def test_party_tokens_and_split_parties():
    assert split_parties("NAVTEJ SINGH JOHAR & ORS. versus UNION OF INDIA") == ("NAVTEJ SINGH JOHAR & ORS.", "UNION OF INDIA")
    assert party_tokens("Suresh Kumar Koushal & Anr. v. Naz Foundation & Ors.") == {"suresh", "kumar", "koushal", "naz", "foundation"}
    assert jaccard({"a", "b"}, {"b", "c"}) == 1 / 3
    assert jaccard(set(), set()) == 0.0


def test_same_parties_ignores_government_side_and_is_order_insensitive():
    assert same_parties("M. A. Antony @ Antappan v. State of Kerala", "State of Kerala v. M.A. Antony @ Antappan")
    assert not same_parties("State of Maharashtra v. Ramesh Patil", "State of Maharashtra v. Suresh Jadhav")
    assert not same_parties("Bachan Singh v. State of Punjab", "")


def test_common_names_alone_are_not_the_same_dispute():
    # Two different people called Ram Singh: before the fix this matched, and a real overruling would have been
    # dropped as "appeal history".
    assert not same_parties("Ram Singh v. State of Haryana", "Ram Singh v. State of U.P.")
    assert not same_parties("Ram Lal v. State of U.P.", "State of U.P. v. Ram Lal")
    w = "With respect, [[Ram Singh v. State of U.P. (1990) 2 SCC 1]] is overruled."
    assert not is_appeal_history(w, "Ram Singh v. State of Haryana", "Ram Singh v. State of U.P.", cited_is_sc=True)
    # the State's side is not a party name: two accused called Ram Singh, both prosecuted in Haryana
    assert not same_parties("Ram Singh v. State of Haryana", "State of Haryana v. Ram Singh")
    # a token frequent across the corpus (the resolver's stop list) is not distinctive either
    assert same_parties("Karnail Bisoi v. State of Orissa", "State of Orissa v. Karnail Bisoi")
    assert not same_parties("Karnail Bisoi v. State of Orissa", "State of Orissa v. Karnail Bisoi", common={"karnail", "bisoi"})


def test_appeal_history_rules():
    # the earlier round of the same dispute
    assert is_appeal_history("...", "Dayanidhi Bisoi v. State of Orissa", "State of Orissa v. Dayanidhi Bisoi", cited_is_sc=True)
    # a High Court decision under appeal or set aside is a reversal, not an overruling
    w = "The two-Judge bench over-ruled the decision of the Delhi High Court in Naz Foundation, which was set aside."
    assert is_appeal_history(w, "Suresh Kumar Koushal v. Naz Foundation", "Naz Foundation v. Govt. of NCT of Delhi", cited_is_sc=False)
    assert is_appeal_history("The impugned judgment of the High Court cannot stand.", "A v. B", "C v. D", cited_is_sc=False)
    # a Supreme Court precedent with different parties is never appeal history
    w = "Suresh Kumar Koushal (supra) needs to be, and is hereby, overruled and the impugned judgment set aside."
    assert not is_appeal_history(w, "Navtej Singh Johar v. Union of India", "Suresh Kumar Koushal v. Naz Foundation", cited_is_sc=True)


def test_clean_text_drops_dotted_scr_running_heads_but_not_case_law_lists():
    raw = "end of para.\n[2018] 11 S.C.R.\n62. The Court held.\n[2014] 11 SCR 1009\nrelied on\n[2018] 13  S.C.R. 296\n"
    assert clean_text(raw) == "end of para. 62. The Court held. [2014] 11 SCR 1009 relied on"
