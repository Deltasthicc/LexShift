# Treatment labelling guide (M3 gold set)

You label how a Supreme Court judgment treats one earlier case it cites. The case is marked in the window with
`[[ ]]`. Read the whole window and choose **one** label for the marked case only. Label by reading. Never label
from a single word: "overruled" in a window does not make the label `overruled`.

## Labels

| Label | Use it when the citing court itself... | Typical wording (only a hint) |
|---|---|---|
| `followed` | relies on, applies, follows or approves the marked case as authority for its own reasoning | "following", "relied on", "the ratio applies", "approved" |
| `distinguished` | says the marked case does not apply here because the facts or the question differ | "distinguishable", "has no application", "decided on different facts" |
| `doubted` | disagrees with, criticises or doubts the marked case, calls it per incuriam, or refers it to a larger bench, **without** overruling it | "we have our doubts", "requires reconsideration", "per incuriam", "refer to a larger Bench" |
| `overruled` | itself explicitly overrules the marked case, or declares it no longer good law | "is hereby overruled", "stands overruled", "does not lay down the correct law" (when the court is deciding that) |
| `neutral` | only mentions, lists, quotes, summarises or describes the marked case, or reports counsel's argument, without evaluating it | "reference was made to", "counsel relied on", "in X the Court held..." |

## Rules for the hard cases

1. **Set aside, reversed or quashed on appeal is never `overruled`.** It reverses the decision under appeal. Such
   windows are usually filtered out as appeal history. If one reaches you, label it `neutral`.
2. **"Objection overruled" or "contention overruled"** is about an argument, not a precedent. Label it `neutral`.
3. **Reported treatment by another court is `neutral`.** "In X, this Court overruled [[Y]]" describes what X did.
   The citing court is not overruling Y in this window, so the label is `neutral`. That edge is captured from X's
   own text if X is in the corpus.
4. **The overruling case is not overruled.** In "Following [[Navtej Johar]], Koushal stands overruled", Navtej Johar
   is `followed`.
5. **Headnote case-law lists** ("... (2014) 1 SCC 1 – overruled"; "– relied on"; "– referred to"): the reporter is
   summarising what this judgment did, so label what it says (`overruled`, `followed`, `neutral`). "Referred to" is
   `neutral`. "Held inapplicable" is `distinguished`.
6. **Counsel's submissions** ("learned counsel relied on [[X]]") are `neutral`, unless the court then adopts or
   rejects X in its own voice within the same window.
7. **Partial treatment** (overruled "to the extent that...", "on this point"): use the label for that point. Write
   the point in `notes`.
8. **Unsure between `neutral` and anything else:** choose `neutral` and write why in `notes`.

## Process

- Labeller 1 fills `m3_L1.csv`. Labeller 2 independently fills `m3_L2.csv` (a subset, for Cohen's kappa). Do not
  look at each other's sheets or at `candidates.csv` (it shows which cue bucket found the window).
- Fill only the `gold_label` column (and `notes` if useful). Leave `labeller` as it is.
- Then run `python -m m3_treatment.gold merge`. It refuses while any window is blank (use `--allow-incomplete` for a
  partial look). It also refuses if a sheet is missing or would lose a typed adjudication. Disagreements go to `disagreements.csv`. Re-read each one together
  and fill `adjudicated`, then run merge again.
- Record who labelled what in `AI_USE_LOG.md`: no model may produce these labels.
