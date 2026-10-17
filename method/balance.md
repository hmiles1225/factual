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
