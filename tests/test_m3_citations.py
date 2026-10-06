import pytest

from m3_treatment.citations import alias_phrases, extract_citations, extract_mentions, find_case_names, find_cites, parse_cite


@pytest.mark.parametrize(
    "raw,key,is_sc",
    [
        ("(2014) 1 SCC 1", "SCC|2014|1||1", True),
        ("2010 (11) SCC 175", "SCC|2010|11||175", True),
        ("(1993) 1 Suppl. SCC 96", "SCC|1993|1|S|96", True),
        ("(2013) 4 SCC (Cri) 1", "SCC|2013|4||1", True),
        ("[2013] 17 SCR 116", "SCR|2013|17||116", True),
        ("[2018] 10 S.C.R. 1005", "SCR|2018|10||1005", True),
        ("[2004] 4 Suppl. SCR 464", "SCR|2004|4|S|464", True),
        ("1955 SCR 1", "SCR|1955|||1", True),
        ("AIR 1973 SC 1461", "AIR|1973|SC||1461", True),
        ("A.I.R. 1973 S.C. 1461", "AIR|1973|SC||1461", True),
        ("AIR 1953 Bom 311", "AIR|1953|Bom||311", False),
        ("2018 INSC 696", "INSC|2018|||696", True),
        ("2018:INSC:696", "INSC|2018|||696", True),
        ("(2018) SCC OnLine SC 275", "SCC_ONLINE|2018|SC||275", True),
        ("2018 (6) SCALE 174", "SCALE|2018|6||174", True),
        ("2003 Crl.L.J. 3697 (SC)", "CRILJ|2003|||3697", True),
    ],
)
def test_reporter_formats(raw, key, is_sc):
    c = parse_cite(raw)
    assert c is not None and c.key == key and c.is_sc == is_sc


def test_page_header_without_page_is_not_a_citation():
    assert find_cites("[2018] 13 S.C.R. M. A. ANTONY v. STATE OF KERALA") == []


def test_case_names_stop_at_sentence_and_list_boundaries():
    text = (
        "[2014] 12 SCR 875 Cheviti Venkanna Yadav v. State of Telangana & Ors. (2017) 1 SCC 283 ; "
        "In Dayanidhi Bisoi v. State of Orissa, the Court held. Mohd. Arif alias Ashfaq v. The Registrar Supreme Court "
        "of India & others (2014) 9 SCC 737. Rajendra Pralhadrao Wasnik v. State of Maharashtra Decided on 2019. "
        "Manoj V. George was a witness."
    )
    names = [n.name for n in find_case_names(text)]
    assert names == [
        "Cheviti Venkanna Yadav v. State of Telangana & Ors.",
        "Dayanidhi Bisoi v. State of Orissa",
        "Mohd. Arif alias Ashfaq v. The Registrar Supreme Court of India & others",
        "Rajendra Pralhadrao Wasnik v. State of Maharashtra",
    ]


def test_full_name_and_cite_mentions_with_parallel_citations():
    text = (
        "Bachan Singh v. State of Punjab (1980) 2 SCC 684 – relied on. Suresh Kumar Koushal and Anr. v. Naz Foundation "
        "and Ors. (2014) 1 SCC 1 : [2013] 17 SCR 116 – overruled. See also (1985) 1 SCC 505; State of U.P. v. M.K. Anthony."
    )
    ms = extract_mentions(text)
    kinds = [(m.kind, [c.key for c in m.cites]) for m in ms]
    assert kinds[0] == ("full", ["SCC|1980|2||684"])
    assert kinds[1] == ("full", ["SCC|2014|1||1", "SCR|2013|17||116"])
    assert ("cite", ["SCC|1985|1||505"]) in kinds
    assert ms[-1].kind == "name" and ms[-1].name == "State of U.P. v. M.K. Anthony"


def test_supra_and_alias_link_back_to_the_cited_full_mention():
    text = (
        "Suresh Kumar Koushal & Anr. v. Naz Foundation & Ors. (2014) 1 SCC 1 was argued. "
        "Later, Suresh Kumar Koushal & Anr. v. Naz Foundation & Ors. was discussed. "
        "Suresh Kumar Koushal (supra) needs to be, and is hereby, overruled. The decision in Koushal stands overruled."
    )
    ms = extract_mentions(text)
    full = next(i for i, m in enumerate(ms) if m.kind == "full")
    supra = next(m for m in ms if m.kind == "supra")
    alias = next(m for m in ms if m.kind == "alias")
    assert supra.name == "Suresh Kumar Koushal" and supra.antecedent == full  # the cited antecedent, not the later bare name
    assert alias.raw(text) == "Koushal" and alias.antecedent == full


def test_alias_needs_a_distinctive_word():
    assert alias_phrases("Suresh Kumar Koushal & Anr. v. Naz Foundation & Ors.") == ["Suresh Kumar Koushal", "Koushal"]
    assert alias_phrases("Bachan Singh v. State of Punjab") == ["Bachan Singh"]  # "Singh" alone is too common
    assert alias_phrases("State of Punjab v. Devans Modern Breweries Ltd.") == ["Devans Modern Breweries Ltd", "Breweries"]
    assert alias_phrases("Sushil Kumar v. State of Punjab") == ["Sushil Kumar"]


def test_alias_never_matches_lower_case_prose():
    text = "Joseph Shine v. Union of India (2019) 3 SCC 39 was cited. The sun did shine. Shine (supra) applies."
    ms = extract_mentions(text)
    assert [m.raw(text) for m in ms if m.kind == "alias"] == []
    assert [m.kind for m in ms] == ["full", "supra"]


def test_extract_citations_returns_plain_dicts():
    out = extract_citations("Bachan Singh v. State of Punjab (1980) 2 SCC 684 held so.")
    assert out == [
        {
            "start": 0,
            "end": 48,
            "kind": "full",
            "name": "Bachan Singh v. State of Punjab",
            "cited_raw": "Bachan Singh v. State of Punjab (1980) 2 SCC 684",
            "cites": ["SCC|1980|2||684"],
            "year": 1980,
            "antecedent": None,
        }
    ]
