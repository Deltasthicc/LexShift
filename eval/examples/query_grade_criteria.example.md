# Candidate query grading criteria

This is a review aid for the 30 candidates in `queries.example.jsonl`, not a qrels file and not a source of labels. A query does
not receive one grade: every pooled `(qid, doc_id)` pair is graded after two people independently read the actual judgment. Copy
none of the examples into `eval/qrels.tsv`.

## One rule for every query

* **2:** the judgment materially answers the queried point and remains authoritative for that point and date.
* **1:** it materially answers the point, but the governing statute materially changed, or a later court criticised or doubted
  the rule without overruling it on that point.
* **0:** it is irrelevant or merely mentions the topic, uses the colliding section number for the wrong code/date, or was
  overruled on the queried point.

Grade a partial overruling only on the queried point. A case merely distinguished on different facts is not automatically a 1.
For types A, B and D, apply the offence date. For type C, verify the later judgment and bench before using the candidate.

## Type A — new-code query needing old-code precedent

| qid | Grade 2 anchor | Grade 1 anchor | Grade 0 anchor |
|---|---|---|---|
| dev01 | Directly interprets murder elements or punishment preserved from IPC 302 in BNS 103. | On point, but weakened on the queried proposition. | A different section 103, a passing murder reference, or an overruled queried rule. |
| dev02 | Directly addresses dishonest inducement and delivery of property carried from IPC 420 into BNS 318. | On point only to an IPC-420 feature materially reorganised or changed in BNS 318. | Other cheating variants, a civil dispute with no cheating issue, or a passing reference. |
| dev03 | Directly addresses dowry-death elements or the statutory presumption carried from IPC 304B into BNS 80. | On point, but a material statutory or precedential qualification applies. | IPC 80 accident cases, ordinary homicide, or a passing dowry reference. |
| test01 | Directly explains joint liability through common intention under IPC 34/BNS 3(5). | On point, but criticised or doubted on the queried test. | Common object, conspiracy, or mere presence without deciding common intention. |
| test02 | Directly explains agreement and liability for criminal conspiracy under IPC 120A/120B or BNS 61. | On point, but a material new-code or later-treatment qualification applies. | Mere association, common intention, or a passing conspiracy allegation. |
| test03 | Directly decides the definition of rape or consent carried from IPC 375 into BNS 63. | On point, but the exact element or exception materially changed or was criticised. | A sentencing-only IPC 376 case or a passing allegation. |
| test04 | Directly decides punishment for rape carried from IPC 376 into BNS 64. | On point, but tied to a punishment band or circumstance materially changed in the new code. | Definition/consent only, a different sexual offence, or a passing reference. |
| test05 | Directly decides the High Court's inherent power to quash criminal proceedings under CrPC 482/BNSS 528. | On point, but criticised/doubted or dependent on a procedural feature that changed. | A merits appeal, discharge under another provision, or a passing FIR reference. |
| test16 | Directly decides intention/knowledge and the overt act for attempt to murder under IPC 307/BNS 109. | On point, but dependent on an old punishment detail or later criticised test. | Completed murder, hurt without the attempted-murder issue, or a passing section reference. |

## Type B — changed, omitted or new provisions

| qid | Grade 2 anchor | Grade 1 anchor | Grade 0 anchor |
|---|---|---|---|
| dev04 | Directly interprets the current BNS 152 offence or authoritatively explains the present legal position. | Interprets IPC 124A and is useful background, but BNS 152 is a different offence. | Treats IPC 124A as unchanged and controlling, or merely mentions sedition. |
| dev05 | Directly answers the current, narrow BNS 226 offence or authoritatively explains that ordinary attempted suicide is omitted. | Directly interprets IPC 309, but the post-2024 law materially changed. | *P. Rathinam* on the right-to-die point, which *Gian Kaur* overruled, or a passing suicide reference. |
| test06 | *Joseph Shine* or another authoritative judgment explaining that adultery is not a criminal offence. | A relevant collateral or historical treatment not overruled on its own point. | An earlier decision upholding IPC 497 on the queried criminal-validity point, or a matrimonial dispute only. |
| test07 | Directly interprets the group, concert and specified-ground elements of BNS 103(2). | IPC-era group-murder/common-object law that is useful but does not decide the new specified-ground element. | Ordinary murder with no group-offence issue or a passing mob reference. |
| test08 | Directly interprets organised crime and criminal-syndicate elements under BNS 111. | MCOCA or another special-statute precedent useful only by analogy. | Ordinary conspiracy or repeat offending without the organised-crime issue. |
| test09 | Directly interprets terrorist-act elements under BNS 113. | UAPA precedent useful by analogy but not controlling the BNS provision. | Ordinary public-order or violent-crime material with no terrorist-act issue. |

## Type C — later treatment of a doctrine

| qid | Grade 2 anchor | Grade 1 anchor | Grade 0 anchor |
|---|---|---|---|
| dev06 | *Navtej Singh Johar* or later authority applying its rule on consensual adult same-sex relations. | On point but later criticised/doubted without overruling. | *Suresh Kumar Koushal* on the point expressly overruled by *Navtej*. |
| dev07 | *Sushila Aggarwal* or later authority applying the rule that anticipatory bail need not end after a fixed period. | On point but later criticised/doubted without overruling. | *Salauddin* and followers on mandatory time limitation; *Siddharam Mhetre* is 0 only on the separate no-conditions proposition overruled to that extent. |
| dev08 | *Social Action Forum for Manav Adhikar* or later authority rejecting court-created Family Welfare Committees under section 498A. | A surviving part of *Rajesh Sharma* relevant to a different queried safeguard, or a later doubted rule. | *Rajesh Sharma* on the Family Welfare Committee direction that the later larger bench did not accept. |
| test10 | *Joseph Shine* or later authority applying the invalidation of IPC 497. | On point but later criticised/doubted without overruling. | *Sowmithri Vishnu* or *V. Revathi* on the validity point overruled in *Joseph Shine*. |
| test11 | *K.S. Puttaswamy* or later authority recognising privacy as a fundamental right. | On point but later criticised/doubted without overruling. | *ADM Jabalpur* on the liberty proposition expressly overruled in *Puttaswamy*, or a privacy mention unrelated to the legal question. |
| test17 | *Anvar P.V.*, *Arjun Panditrao*, or later authority applying the mandatory section 65B route, subject to the original-device clarification. | On point but later criticised/doubted without overruling. | *Navjot Sandhu*, *Shafhi Mohammad*, or *Tomaso Bruno* on the contrary certificate proposition displaced by the later larger bench. |
| test18 | *Tofan Singh* or later authority applying inadmissibility of a section 67 NDPS confession. | On point but later criticised/doubted without overruling. | *Kanhaiyalal* or *Raj Kumar Karwal* on the contrary confession proposition overruled by *Tofan Singh*. |
| test19 | *Mukesh Singh* or later authority holding that identity of informant and investigator does not automatically vitiate the case, while allowing proof of actual bias. | On point but later criticised/doubted, or finding fact-specific bias without adopting an automatic rule. | *Mohan Lal* on automatic vitiation, expressly overruled by *Mukesh Singh*. |
| test20 | *High Court Bar Association, Allahabad* or later authority rejecting automatic vacation solely after six months. | On point but later criticised/doubted without overruling. | *Asian Resurfacing* on the automatic-vacation direction displaced by the Constitution Bench. |

## Type D — bare-number collisions

| qid | Grade 2 anchor | Grade 1 anchor | Grade 0 anchor |
|---|---|---|---|
| dev09 | For the 2020 date, directly decides IPC 80 accident in a lawful act. | On point but later criticised/doubted. | BNS 80 dowry-death material or another section 80. |
| dev10 | For the 2025 date, directly decides BNS 80/IPC 304B dowry death. | An IPC 304B case on a materially changed or weakened point. | IPC 80 accident material or another section 80. |
| test12 | For the 2020 date, directly decides when IPC 103 extends private defence of property to causing death. | On point but later criticised/doubted. | BNS 103 murder material or another section 103. |
| test13 | For the 2025 date, directly decides BNS 103/IPC 302 murder. | An IPC 302 case on a materially changed or weakened point. | IPC 103 private-defence material or another section 103. |
| test14 | For the 2020 date, directly decides IPC 318 concealment of birth. | On point but later criticised/doubted. | BNS 318 cheating material or another section 318. |
| test15 | For the 2025 date, directly decides BNS 318 cheating. | An IPC cheating case on a materially reorganised or weakened point. | IPC 318 concealment-of-birth material or another section 318. |

## Primary-source anchors to verify before adoption

* Statutory text: [BNS 2023 (India Code)](https://www.indiacode.nic.in/bitstream/123456789/20062/1/a2023-45.pdf) and
  [IPC 1860 (India Code)](https://www.indiacode.nic.in/bitstream/123456789/4219/1/THE-INDIAN-PENAL-CODE-1860.pdf).
* Anticipatory bail: [*Sushila Aggarwal v. State (NCT of Delhi)*](https://api.sci.gov.in/supremecourt/2017/28027/28027_2017_3_1501_20088_Judgement_29-Jan-2020.pdf).
* Section 377: [*Navtej Singh Johar v. Union of India*](https://api.sci.gov.in/supremecourt/2016/14961/14961_2016_Judgement_06-Sep-2018.pdf).
* Privacy: [*K.S. Puttaswamy v. Union of India*](https://www.api.sci.gov.in/supremecourt/2012/35071/35071_2012_Judgement_24-Aug-2017.pdf).
* Adultery: [*Joseph Shine v. Union of India*](https://api.sci.gov.in/supremecourt/2017/32550/32550_2017_Judgement_27-Sep-2018.pdf).
* Electronic evidence: [Supreme Court judgment reproducing *Arjun Panditrao*'s controlling conclusion](https://api.sci.gov.in/supremecourt/2011/29890/29890_2011_1_1502_39505_Judgement_03-Nov-2022.pdf).
* NDPS section 67: [*Tofan Singh v. State of Tamil Nadu*](https://api.sci.gov.in/supremecourt/2012/26682/26682_2012_33_1501_24551_Judgement_29-Oct-2020.pdf).
* Informant/investigator: [*Mukesh Singh v. State (Narcotic Branch of Delhi)*](https://api.sci.gov.in/supremecourt/2018/39528/39528_2018_33_1502_23731_Judgement_31-Aug-2020.pdf).
* Six-month stay direction: [*High Court Bar Association, Allahabad v. State of U.P.*](https://api.sci.gov.in/supremecourt/2023/47928/47928_2023_1_1501_51053_Judgement_29-Feb-2024.pdf).

The remaining mapping and treatment propositions come from the project brief and must still be checked by a team member against
the judgments and an official/independent statutory source before the candidate moves to `eval/queries.jsonl`.
