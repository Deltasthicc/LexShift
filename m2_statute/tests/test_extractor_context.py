"""The extractor's reading of bare sections from the rest of the judgment, the forms it understands, and the query parser's use of the offence date."""

from __future__ import annotations

import pytest

from m2_statute.extractor import extract_refs, family_of, normalize_act, offence_id
from m2_statute.mapping import base_section, relation_between
from m2_statute.matcher import best_match
from m2_statute.mapping import load_map
from m2_statute.query_parser import parse_query


def pairs(text: str, when: str = "2019-05-01") -> dict[tuple[str, str], int]:
    return {(r.act, r.section): r.count for r in extract_refs(text, when)}


@pytest.mark.parametrize("text, expected", [
    ("u/s 302 IPC", ("IPC", "302")),
    ("S. 302 I.P.C.", ("IPC", "302")),
    ("Section 482 Cr.P.C.", ("CRPC", "482")),
    ("Section 438 of the Code of Criminal Procedure", ("CRPC", "438")),
    ("Section 63 of the Bharatiya Nyaya Sanhita", ("BNS", "63")),
    ("BNS 3(5)", ("BNS", "3(5)")),
    ("IPC 120-B", ("IPC", "120B")),
    ("Section 34 of the Penal Code", ("IPC", "34")),
    ("Section 528 BNSS", ("BNSS", "528")),
])
def test_the_forms_judgments_use(text: str, expected: tuple[str, str]) -> None:
    assert expected in pairs(text)


def test_a_list_of_sections_shares_the_act_that_follows() -> None:
    got = pairs("convicted under Sections 302, 307 and 34 of the Indian Penal Code")
    assert {("IPC", "302"), ("IPC", "307"), ("IPC", "34")} <= set(got)


def test_the_code_is_resolved_by_the_judgment_date() -> None:
    assert pairs("Section 438 of the Code", "2019-05-01") == {("CRPC", "438"): 1}
    assert pairs("Section 438 of the Code", "2025-05-01") == {("BNSS", "438"): 1}


def test_a_bare_section_takes_the_nearest_explicit_act_of_its_family() -> None:
    text = ("The appellant was charged under Section 302 of the Indian Penal Code. " + "Facts. " * 400 +
            "Section 34 was also invoked. " + "More facts. " * 400 + "Section 439 of the Cr.P.C. was relied on, and Section 438 as well.")
    got = pairs(text)
    assert got[("IPC", "34")] == 1  # substantive: the Indian Penal Code mention, however far back
    assert got[("CRPC", "438")] == 1  # procedural: the Cr.P.C. mention
    assert not any(act == "UNKNOWN" for act, _ in got)


def test_a_section_the_map_does_not_know_needs_an_explicit_act_in_the_same_paragraph() -> None:
    near = pairs("Section 148 and Section 149 of the Indian Penal Code were charged. Section 147 too.")
    assert near[("IPC", "147")] == 1  # same paragraph, a few characters after an explicit IPC
    far = pairs("Section 302 IPC.\n\n" + "Unrelated text. " * 80 + "Section 147 was charged.")
    assert far[("UNKNOWN", "147")] == 1  # too far and in another paragraph


def test_no_explicit_act_anywhere_leaves_the_section_unknown_not_guessed() -> None:
    assert pairs("Section 302 was invoked.") == {("UNKNOWN", "302"): 1}


def test_a_section_of_another_act_is_not_a_reference_to_the_four_codes() -> None:
    got = pairs("Section 302 IPC. Section 37 of the NDPS Act and Section 27 of the Evidence Act were also relied on. Section 13(2) of the Prevention of Corruption Act.")
    assert got == {("IPC", "302"): 1}


def test_offence_ids_come_from_the_map_and_follow_the_provision_across_the_codes() -> None:
    assert offence_id("IPC", "302") == offence_id("BNS", "103") == "OFF_MURDER"
    assert offence_id("CRPC", "438") == offence_id("BNSS", "482") == "OFF_ANTICIPATORY_BAIL"
    assert offence_id("CRPC", "438(1)") == "OFF_ANTICIPATORY_BAIL"  # sub-clauses do not matter
    assert offence_id("IPC", "999") is None


def test_code_family_is_read_from_the_map() -> None:
    assert family_of("302") == "substantive"
    assert family_of("438") == "procedural"
    assert family_of("12345") is None


def test_sub_clauses_do_not_hide_a_mapped_provision() -> None:
    assert base_section("3(5)") == "3" and base_section("120-b") == "120B" and base_section("438(1)(a)") == "438"
    row = relation_between("BNS", "3(5)", "IPC", "34")
    assert row is not None and row.relation == "equivalent"
    assert best_match(parse_query("BNS 3(5) common intention").refs, extract_refs("Section 34 IPC", "2019-01-01"), load_map())[0] == 1.0


def test_normalize_act_understands_the_dotted_forms() -> None:
    assert normalize_act("I.P.C.", "2019-01-01") == "IPC"
    assert normalize_act("Cr. P.C.", "2019-01-01") == "CRPC"
    assert normalize_act("Bharatiya Nagarik Suraksha Sanhita", "2019-01-01") == "BNSS"
    assert normalize_act("Bharatiya Nyaya Sanhita", "2019-01-01") == "BNS"


# ---------------------------------------------------------------------------------------------------------------- the query parser
def test_a_bare_section_in_a_query_takes_its_code_from_the_offence_date() -> None:
    assert [(r.act, r.section) for r in parse_query("section 103", "2025-02-01").refs] == [("BNS", "103")]
    assert [(r.act, r.section) for r in parse_query("section 103", "2020-06-01").refs] == [("IPC", "103")]
    assert [(r.act, r.section) for r in parse_query("section 438 bail", "2020-06-01").refs] == [("CRPC", "438")]  # procedural, by the map
    assert [(r.act, r.section) for r in parse_query("section 438 bail", "2025-02-01").refs] == [("BNSS", "438")]


def test_without_an_offence_date_a_bare_section_stays_unknown_and_says_so() -> None:
    qs = parse_query("section 377 consensual relations")
    assert [(r.act, r.section) for r in qs.refs] == [("UNKNOWN", "377")]
    assert any("no offence date" in n for n in qs.notes)
