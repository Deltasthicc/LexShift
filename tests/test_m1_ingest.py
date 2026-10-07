"""M1 corpus construction: titles, bench parsing, dates, selection rules and the build step's safety (no network, no real PDFs)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from m1_index import catalog, ingest, selection
from m1_index.catalog import Entry


def _entry(path: str = "2018_14_828_839", year: int = 2018, title: str = "STATE versus X", pdf_bytes: int | None = 1000, date: str = "14-12-2018") -> Entry:
    return Entry(path=path, year=year, title=title, petitioner="", respondent="", judge="", citation="2018 INSC 1", case_id="CRIMINAL APPEAL NO. 1 of 2018",
                 decision_date=date, disposal_nature="Allowed", pdf_bytes=pdf_bytes)


# ---------------------------------------------------------------------------------------------------------------------- titles
@pytest.mark.parametrize("raw, expected", [
    ("V. RAVI KUMAR versus STATE, REP. BY INSPECTOR OF POLICE & ORS.", "V. Ravi Kumar v. State, Rep. by Inspector of Police & Ors."),
    ("K.S. PUTTASWAMY versus UNION OF INDIA", "K.S. Puttaswamy v. Union of India"),
    ("CBI versus STATE OF U.P.", "CBI v. State of U.P."),
    ("  STATE   OF TAMIL NADU versus  TOFAN SINGH ", "State of Tamil Nadu v. Tofan Singh"),
    ("STATE THROUGH CBI, CHENNAI versus V. ARUL KUMAR", "State through CBI, Chennai v. V. Arul Kumar"),  # an initial V. is not "versus"
    ("A. V. RAO versus THE STATE OF GOA", "A. V. Rao v. The State of Goa"),
])
def test_smart_title(raw: str, expected: str) -> None:
    assert ingest.smart_title(raw) == expected


def test_smart_title_does_not_leave_shouting_words() -> None:
    title = ingest.smart_title("HIGH COURT BAR ASSOCIATION, ALLAHABAD versus STATE OF U.P. & ORS.")
    assert "HIGH" not in title and "BAR" not in title
    assert title.startswith("High Court Bar Association, Allahabad v. State of U.P.")


def test_smart_title_empty() -> None:
    assert ingest.smart_title("") == ""
    assert ingest.smart_title(None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------------------------------- coram
def test_coram_names_and_bench_size() -> None:
    size, judges = ingest.parse_coram_bench_size("[J.S. VERMA, G.N. RAY, N.P. SINGH, FAIZAN UDDIN\nB\nAND G.T. NANAVATI, JJ.]")
    assert size == 5
    assert "FAIZAN UDDIN" in judges  # the margin letter B on the next line is not part of the name
    assert not any(j.endswith(" B") for j in judges)


def test_coram_ocr_closing_bracket() -> None:
    size, judges = ingest.parse_coram_bench_size("[Y.V. CHANDRACHUD, C.J., R.S. PATHAK AND AMARENDRA\nNATN SEN, JJ.J")
    assert size == 3
    assert judges[-1] == "AMARENDRA NATN SEN"


@pytest.mark.parametrize("text, expected", [
    ("[M.Y. EQBALAND C. NAGAPPAN, JJ.]", ["M.Y. EQBAL", "C. NAGAPPAN"]),  # AND glued to the name before it
    ("[M.Y. EQBALANDAMITAVA ROY, JJ.]", ["M.Y. EQBAL", "AMITAVA ROY"]),
    ("[MADAN 8. LOKUR ANDS. A. BOBDE, JJ.]", ["MADAN B. LOKUR", "S. A. BOBDE"]),  # 8 for B, ANDS. for AND S.
    ("[KURIAN JOSEPH AND.A.M. KIIANWILKAR, JJ.]", ["KURIAN JOSEPH", "A.M. KIIANWILKAR"]),
    ("(M.Y.EQBAL AND SHIVA KIRTI SINGH, JJ.)", ["M.Y.EQBAL", "SHIVA KIRTI SINGH"]),  # round brackets
    ("[A.K. SIKRI AND ABHAY MANOHAR SAPRE, JJ,I", ["A.K. SIKRI", "ABHAY MANOHAR SAPRE"]),  # closing bracket read as I
    ("[R. F. NARIMAN AND\nMOHAN M. SHANTANAGOUDAR, JJ.I", ["R. F. NARIMAN", "MOHAN M. SHANTANAGOUDAR"]),
    ("FEBRUARY 25, 1988\nIM.P. THAKKAR AND MUAARI MOHQN DUTI, JJ.]", ["M.P. THAKKAR", "MUAARI MOHQN DUTI"]),  # the opening bracket is lost
    ("[PINAKI CHANDRA GHOSE, J.]", ["PINAKI CHANDRA GHOSE"]),
    ("OCTOBER 25, 2019\n[UDAY UMESH LALIT,  INDU MALHOTRA AND\nR. SUBHASH REDDY]\nCode of Criminal Procedure", ["UDAY UMESH LALIT", "INDU MALHOTRA", "R. SUBHASH REDDY"]),  # no "JJ." at all
    ("[M. R. SHAH, JJ. AND KRISHNA MURARI]\nPenal Code", ["M. R. SHAH", "KRISHNA MURARI"]),
    ("PATHUBHA GOVIND, J.\n[DIPAK MISRA AND PRAFULLA C. PANT, JJ.]", ["DIPAK MISRA", "PRAFULLA C. PANT"]),  # the real bracket wins over an earlier stray ", J."
])
def test_coram_ocr_variants(text: str, expected: list[str]) -> None:
    size, judges = ingest.parse_coram_bench_size(text)
    assert judges == expected and size == len(expected)


def test_a_list_of_cited_cases_is_not_a_bench() -> None:
    junk = "263-F-H; Ramesh Kumar vs. State (2001) 9 SCC 618 : [2001) 4 Suppl. SCR 247 referred to Para 7 Criminal Appeal No. 790 of 2017. From the Judgment, J."
    assert ingest.parse_coram_bench_size(junk) == (None, [])
    assert ingest.parse_coram_bench_size("He said so, J. I agree with this") == (None, [])


def test_coram_without_a_bench_line_is_unknown_not_invented() -> None:
    assert ingest.parse_coram_bench_size("no coram line at all") == (None, [])


def test_chief_justice_marker_is_not_a_judge() -> None:
    size, judges = ingest.parse_coram_bench_size("[D.Y. CHANDRACHUD, CJI, J.B. PARDIWALA AND MANOJ MISRA, JJ.]")
    assert size == 3
    assert not any("CJI" in j.upper() for j in judges)


# ---------------------------------------------------------------------------------------------------------------------- dates and text
def test_catalog_date() -> None:
    assert ingest.catalog_date("14-12-2018") == "2018-12-14"
    assert ingest.catalog_date("1-2-1976") == "1976-02-01"
    assert ingest.catalog_date("31-02-2018") is None  # not a calendar date
    assert ingest.catalog_date("") is None
    assert ingest.catalog_date("2018-12-14") is None  # another format: the caller falls back to parse_iso_date


def test_clean_text_removes_control_characters_but_keeps_lines() -> None:
    text = "Line one\x0c\nLine\x00 two­word  \n\n\n\n\n\nEnd"
    out = ingest.clean_text(text)
    assert "\x00" not in out and "\x0c" not in out and "­" not in out
    assert "Line one" in out and "Line twoword" in out
    assert out.count("\n\n\n\n") == 0


# ---------------------------------------------------------------------------------------------------------------------- selection rules
def test_named_cases_match_title_and_year_only() -> None:
    right = _entry("2018_10_1_2", 2018, "NAVTEJ SINGH JOHAR versus UNION OF INDIA")
    wrong_year = _entry("2005_1_1_2", 2005, "NAVTEJ SINGH JOHAR versus UNION OF INDIA")
    no_pdf = _entry("2018_10_9_9", 2018, "NAVTEJ SINGH JOHAR versus UNION OF INDIA", pdf_bytes=None)
    matched = selection.named_matches([right, wrong_year, no_pdf])
    assert [e.path for _, e in matched] == ["2018_10_1_2"]
    assert matched[0][0].doctrine == "section 377" and matched[0][0].role == "overruling"


def test_every_judged_doctrine_has_both_ends() -> None:
    by_doctrine: dict[str, set[str]] = {}
    for n in selection.NAMED:
        by_doctrine.setdefault(n.doctrine, set()).add(n.role)
    for doctrine, roles in by_doctrine.items():
        if "related" in roles and len(roles) == 1:
            continue  # sedition, mob lynching: judged queries but not overruling pairs
        assert {"overruled", "overruling"} <= roles, doctrine


def test_candidates_tiers_and_order() -> None:
    entries = [
        _entry("2020_1_1_2", 2020, "STATE OF X versus Y"),
        _entry("2020_1_3_4", 2020, "ACME LTD versus BETA LTD"),
        _entry("2021_1_1_2", 2021, "CENTRAL BUREAU OF INVESTIGATION versus Z"),
        _entry("2010_1_1_2", 2010, "STATE OF X versus Y"),
        _entry("2021_1_5_6", 2021, "STATE versus W", pdf_bytes=None),
    ]
    got = selection.candidates(entries, [2021, 2020])
    assert [e.path for e in got] == ["2021_1_1_2", "2020_1_1_2"]  # newest first; civil title, other year and missing PDF left out
    assert [e.path for e in selection.candidates(entries, [2020], tier="all")] == ["2020_1_1_2", "2020_1_3_4"]


def test_criminal_text_filter() -> None:
    assert selection.is_criminal_text("The accused was charged under Section 302 of the Indian Penal Code.")
    assert selection.is_criminal_text("Offences under the NDPS Act were alleged.")
    assert selection.is_criminal_text("Section 482 of the Cr.P.C. was invoked.")
    assert not selection.is_criminal_text("The tenant failed to pay rent under the Transfer of Property Act.")


# ---------------------------------------------------------------------------------------------------------------------- years and plan
def test_parse_years() -> None:
    assert ingest.parse_years("2025-2023") == [2025, 2024, 2023]
    assert ingest.parse_years("2020-2022") == [2020, 2021, 2022]
    assert ingest.parse_years("2024,2019") == [2024, 2019]
    assert ingest.parse_years("") == []


# ---------------------------------------------------------------------------------------------------------------------- catalog
def test_catalog_roundtrip(tmp_path: Path) -> None:
    f = tmp_path / "catalog.jsonl"
    rec = {"path": "S_1985_1_741_749", "year": 1985, "title": "SOWMITHRI VISHNU versus UNION OF INDIA", "petitioner": "", "respondent": "", "judge": "",
           "citation": "1985 Supp (1) SCR 741", "case_id": "WRIT PETITION 1 of 1985", "decision_date": "27-04-1985", "disposal_nature": "Dismissed", "pdf_bytes": 12345}
    f.write_text(json.dumps(rec) + "\n\n", encoding="utf-8")
    [entry] = catalog.load(f)
    assert entry.doc_id == "S_1985_1_741_749_EN"  # supplementary volumes keep their S_ prefix
    assert entry.pdf_key == "data/pdf/year=1985/english/S_1985_1_741_749_EN.pdf"
    assert catalog.find([entry], "sowmithri union", {1985}) == [entry]
    assert catalog.find([entry], "sowmithri union", {2000}) == []


def test_catalog_load_missing_file_says_how_to_build(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="catalog build"):
        catalog.load(tmp_path / "nope.jsonl")


# ---------------------------------------------------------------------------------------------------------------------- build
CRIMINAL = ("JUDGMENT\n\n1. The appellant was convicted under Section 302 of the Indian Penal Code. " + "The facts of the case are set out below. " * 80 + "\n\n"
            + "\n\n".join(f"{i}. Paragraph {i} of the judgment, about the appeal and the evidence. " * 3 for i in range(2, 14)) + "\n\nThe appeal is dismissed.")
CIVIL = "JUDGMENT\n\n1. The tenant failed to pay the rent. " + "A dispute about a lease and nothing else. " * 80


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    text_dir = tmp_path / "text"
    monkeypatch.setattr(ingest, "TEXT_DIR", text_dir)
    monkeypatch.setattr(ingest, "write_manifest", lambda *a, **k: None)
    entries = [
        _entry("2018_1_1_2", 2018, "STATE versus A"),  # criminal text
        _entry("2018_1_3_4", 2018, "STATE versus B"),  # civil text: kept out
        _entry("2018_1_5_6", 2018, "NAVTEJ SINGH JOHAR versus UNION OF INDIA"),  # named: kept whatever its text
        _entry("2018_1_7_8", 2018, "STATE versus C"),  # no text on disk
        _entry("2018_1_9_9", 2018, "STATE versus D"),  # a scan with no text layer
    ]
    monkeypatch.setattr(ingest, "load_catalog", lambda: entries)
    for path, text in (("2018_1_1_2", CRIMINAL), ("2018_1_3_4", CIVIL), ("2018_1_5_6", CIVIL), ("2018_1_9_9", "tiny")):
        f = text_dir / "2018" / f"{path}_EN.txt"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    return tmp_path


def test_build_keeps_criminal_and_named_and_skips_the_rest(workspace: Path) -> None:
    out = workspace / "judgments.jsonl"
    n = ingest.build(out, log=lambda m: None)
    assert n == 2
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert sorted(r["doc_id"] for r in rows) == ["2018_1_1_2_EN", "2018_1_5_6_EN"]
    assert all(r["date"] == "2018-12-14" for r in rows)
    assert all(set(r["zones"]) <= {"headnote", "facts", "arguments", "holding"} for r in rows)
    assert rows[0]["reporter_citations"] == ["2018 INSC 1 : CRIMINAL APPEAL NO. 1 of 2018"]


def test_a_judgment_without_a_date_is_skipped_not_given_one(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    undated = _entry("2018_1_1_2", 2018, "STATE versus A", date="")
    monkeypatch.setattr(ingest, "load_catalog", lambda: [undated])
    out = workspace / "judgments.jsonl"
    assert ingest.build(out, log=lambda m: None) == 0
    assert not out.exists()


def test_build_with_no_text_leaves_the_existing_corpus_alone(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = workspace / "judgments.jsonl"
    out.write_text('{"doc_id": "previous_corpus_record"}\n' * 10, encoding="utf-8")
    monkeypatch.setattr(ingest, "TEXT_DIR", workspace / "empty")
    assert ingest.build(out, log=lambda m: None) == 0
    assert out.read_text(encoding="utf-8") == '{"doc_id": "previous_corpus_record"}\n' * 10


def test_build_refuses_a_much_smaller_corpus_unless_forced(workspace: Path) -> None:
    out = workspace / "judgments.jsonl"
    out.write_text('{"doc_id": "previous_corpus_record"}\n' * 10, encoding="utf-8")
    assert ingest.build(out, log=lambda m: None) == 0  # 2 records would replace 10
    assert out.read_text(encoding="utf-8").count("previous_corpus_record") == 10
    assert ingest.build(out, force=True, log=lambda m: None) == 2
    assert "previous_corpus_record" not in out.read_text(encoding="utf-8")


def test_pack_and_unpack_restore_the_corpus_byte_for_byte(workspace: Path) -> None:
    out = workspace / "judgments.jsonl"
    ingest.build(out, log=lambda m: None)
    packed = workspace / "corpus" / "judgments.jsonl.xz"
    assert ingest.pack(out, packed, log=lambda m: None) == 2
    assert packed.stat().st_size < out.stat().st_size
    restored = workspace / "again" / "judgments.jsonl"
    assert ingest.unpack(packed, restored, log=lambda m: None) == 2
    assert restored.read_bytes() == out.read_bytes()


def test_unpack_refuses_a_corpus_that_does_not_match_its_checksum(workspace: Path) -> None:
    out = workspace / "judgments.jsonl"
    ingest.build(out, log=lambda m: None)
    packed = workspace / "corpus" / "judgments.jsonl.xz"
    ingest.pack(out, packed, log=lambda m: None)
    packed.with_name("judgments.jsonl.sha256").write_text("0" * 64 + "  judgments.jsonl\n", encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        ingest.unpack(packed, workspace / "x.jsonl", log=lambda m: None)
    assert not (workspace / "x.jsonl").exists()


def test_unpack_without_a_packed_corpus_says_what_to_run(workspace: Path) -> None:
    with pytest.raises(FileNotFoundError, match="download"):
        ingest.unpack(workspace / "none.xz", workspace / "x.jsonl", log=lambda m: None)


def test_build_writes_nothing_partial(workspace: Path) -> None:
    out = workspace / "judgments.jsonl"
    ingest.build(out, log=lambda m: None)
    assert not list(workspace.glob("*.tmp"))


@pytest.mark.parametrize("text, expected", [
    ("A\nWEST BENGAL v. X\nNOVEMBER 24, 2006\n[ARIJIT Pf.SAYAT ANDLOKESHWAR SINGHPANTA,JJ.]\nService Law", ["ARIJIT Pf.SAYAT", "LOKESHWAR SINGHPANTA"]),  # AND glued to the next name
    ("(Civil Appeal No. 1334 of 2013)\nFEBRUARY 13, 2013\n[K.S. RADHAKRISHNAN & DIPAK MISRA, JJ.]\nService Law", ["K.S. RADHAKRISHNAN", "DIPAK MISRA"]),  # an ampersand
    ("JULY 18, 2007\n[DR. ARIJIT PASA YAT AND P.P. NAOLEKAR, Jl]\nPenal Code", ["DR. ARIJIT PASA YAT", "P.P. NAOLEKAR"]),  # closing bracket read as l
    ("NOVEM13ER 21, 2008\n[OR. ARIJIT PASAYAT AND DR. MUKUNDAKAM\n-(\n. .\nSHARMA,JJJ\nPenal", ["OR. ARIJIT PASAYAT", "DR. MUKUNDAKAM -( . . SHARMA"]),  # a stray ( inside the list, JJJ
    ("(Criminal Appeal No. 545 of 2007)\nAPRIL 10, 2008\n(P.P. NAOLEKAR & LOKESHWAR SINGH PANTA, JJ.)", ["P.P. NAOLEKAR", "LOKESHWAR SINGH PANTA"]),  # the case number's bracket is not a coram
])
def test_coram_of_the_2005_to_2008_volumes(text: str, expected: list[str]) -> None:
    size, judges = ingest.parse_coram_bench_size(text)
    assert judges == expected and size == len(expected)
