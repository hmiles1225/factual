# Balance

fACTUAL reads outlets across the spectrum, and no side gets more say because it has more outlets.

## Where an outlet's side comes from

Never from anyone's opinion. Each outlet's side is computed in code from published survey data:
Pew Research Center's News Media Tracker (survey of 9,482 U.S. adults, March 10-16, 2025). Pew
reports the share of Republicans and of Democrats who regularly get news from each outlet. The
numbers are stored as published in `pipeline/feeds.json`.

- Audience lean = Republican users / (Republican + Democratic users). This treats the two parties
  as roughly equal in size.
- Under 0.40 is left, over 0.60 is right, anything between is center.
- An outlet Pew did not ask about is **Unplaced**. Unplaced outlets help find stories but do not count
  toward any side.

This measures who reads an outlet, not what it publishes. Placement by word choice (the
Gentzkow-Shapiro method) is the planned second measure; when the two disagree, the outlet is shown as
Unplaced.

## How it is used

The list has more left-audience outlets than right-audience ones, because most large U.S. outlets
have left-leaning audiences and few right-leaning outlets publish a usable feed. So Today does not
rank by raw outlet count. A story's score is the average, over left, center and right, of the share of
that side's outlets that covered it. Each side counts for a third.

Every story shows its coverage the same way, for example "Left 4 of 10 · Center 2 of 4 · Right 3 of 3".

## Which stories appear (2026-10-18)

- Today has eleven sections (2026-10-19). Politics has 5 stories; Elections, Economy, Immigration, Crime &
  justice, World, Energy & environment, Health, AI & tech, Science and Education have 3 each. Most are grouped over
  the last 48 hours; Energy & environment, Science, Health and Education over a 7-day pool of articles,
  because they move by the week: one outlet covers a story on Monday, another on Wednesday.
- World is news abroad without a U.S. decision at its center; a U.S. action abroad (sanctions, aid, an
  endorsement) stays in Politics.
- Readers choose which sections they follow (first five by default). Every section is still written and
  checked for everyone; the choice only filters what a reader sees.
- When the day's budget runs out, checks wait in section order, so the default five are checked first.
- A story appears only if at least one left-leaning **and** one right-leaning outlet covered it. A
  section with no such story says so instead of filling the slot.
- Each summary reads up to 14 articles, dealt round-robin left, right, center, unplaced (one per
  outlet first), so neither side can fill the summary by publishing more articles.
- Common ground is only what outlets on both sides state in their own text. The confirmation reads
  every article in the story, not just the ones the summary writer cited.
- Every story that appears on Today is kept in the archive, by day (U.S. Eastern).

## Outlets Pew did not survey (2026-10-19)

Pew's 2025 survey covers 17 of the outlets we read. An outlet it did not survey is placed from its
published AllSides Media Bias Rating instead (Left and Lean Left are left-leaning, Center is center,
Lean Right and Right are right-leaning), read from the outlet's AllSides page. AllSides is a category,
not a number, so these outlets count fully toward their side but are not drawn on the Pew audience
chart; the page names them under it. Ratings AllSides marks as low confidence are not used. Within a
side every outlet counts once, and the three sides count equally, so adding outlets to one side spreads
that side's weight rather than adding to it.

## Verdict names on the site

The checker's verdict `Holds up` is shown to readers as **Confirmed**, `Doesn't hold up` as **False**, and
`Missing context` as **Misleading** (Heston, 2026-10-19); each Misleading claim carries a "True, but left out:"
line saying what is missing. The checker's instructions
(method/verdicts.md) keep the name it was tested with, so the display change cannot change its answers.
