# Verdicts

Every checked claim gets exactly one of four verdicts. Each one is always shown as a glyph and a
word, never as color alone.

## The test

**Is the claim true as stated, checked against the newest evidence?**

There is one test, and no claim gets an exception to it. "The newest evidence" means the latest release
of each dataset, found by a freshness check at the time the claim is checked.

| Verdict | Means |
| --- | --- |
| Confirmed | True as stated, on the newest evidence. (Stored in the data as `Holds up`.) |
| Missing context | True as stated, but it leaves out something that changes the picture. |
| Doesn't hold up | Not true as stated. Overstated and out-of-date claims count. |
| Unproven | Not enough evidence either way, yet. |

## Tie-breakers

- **Overstated is Doesn't hold up.** "Measles cases are at an all-time high" is not true as stated,
  even though 2025 had the most cases in over 30 years.
- **Out of date is Doesn't hold up.** "Only half a percent of people are transgender" is not true as
  stated: the newest Williams Institute estimate is 0.8% of U.S. adults. Someone repeating an older
  figure is not lying, so the steelman says where the old figure came from.
- **Missing context needs the claim to be true as stated.** It is for claims that are accurate but
  leave out something that changes the picture, such as a total with no rate.
- **Mixed evidence is Unproven,** and the text says "The evidence is mixed." Never force certainty.
- **A forecast is Unproven.** A prediction stated as fact ("this would save money", "this will cost
  a million jobs") cannot be checked yet. It carries the reasoning flag "Forecast, not a finding" and
  shows the range of credible estimates.
- **Doesn't hold up needs two model families to agree.** If they disagree, the claim publishes as
  Unproven.

## How every check reads

1. **Why this sounds right.** The steelman comes first, before the verdict.
2. **The verdict,** glyph and word.
3. **What the evidence shows.** The rationale never opens with a word that sounds like a verdict
   ("Out of date", "Yes", "Wrong").
4. **Based on,** naming the sources and their release dates.

Claims are rated. People and groups never are.

## Outlets are not evidence

A verdict rests on primary sources: the dataset, the study, the filing, the official count. No news
outlet's reporting settles a verdict, whichever side it leans.

Outlets appear in two places instead:

- **Coverage.** Which outlets covered the story, read from their own feeds over the same 48 hours.
- **Also reported by.** When an outlet's article states the same verified fact, the check lists it,
  for example "Also reported by Fox News, CNN and MS NOW." Code confirms the figure or quote appears
  in that article. Readers can see the fact is not one side's fact.

## Values are not verdicts

Some disagreements are about what matters more, not what is true. Those get no verdict. They go
in "Still open" and are left to the reader.
