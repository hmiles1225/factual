"""Stage 3 on the live site: what the coverage agrees on, and where it differs.

Runs after cluster.py in the hourly scan. For each topic's top stories covered by both left- and
right-leaning outlets (politics 5, environment, science and health 3 each):
  1. Gemini reads the outlets' headlines, summaries and the opening of each article and writes a brief:
     common ground (facts outlets on both sides state), other agreed facts, points where the coverage
     differs (each side's position, with the outlets that take it), and any values question. Every item
     must cite the numbered articles it comes from, or it is dropped.
  2. Agreed facts are confirmed against the cited outlets' own text: a fact stays only if at least
     two different outlets state it. These are consensus reports, labeled as such, not verdicts.
  3. A difference that turns on a fact is checked against primary sources (Gemini checks, code
     verifies every quote, Holds up must follow from the verified quotes alone, and Doesn't hold up
     needs Claude Opus to agree). Checked claims live in the library and are reused.

The library (data/library.json) is read back from the live site at the start of each scan, so work
is paid for once. Spend is capped per day in code. A failure here never blocks the scan: the site
keeps last hour's results.
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check as C  # noqa: E402
from images import ROTATION, face, image_for, image_for_title, rotate  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LIBRARY_URL = "https://hestonmiles.com/factual/data/library.json"
ARCHIVE_URL = "https://hestonmiles.com/factual/data/archive/"
SITE_URL = "https://hestonmiles.com/factual/"
# In this order: when the day's budget runs out, the sections later in the list wait. The first five are the
# ones pre-selected for readers.
TOPIC_QUOTAS = {"politics": 5, "texas": 6, "elections": 3, "economy": 3, "immigration": 3, "crime": 3, "world": 3,
                "environment": 3, "health": 3, "tech": 3, "science": 3, "education": 3}   # Heston's calls, 2026-10-18 to -19
EXTRA_CANDIDATES = 3             # stories tried past the quota, in rank order, when one won't summarize
ARTICLES_PER_BRIEF = 14          # picked round-robin by side, so one side can't fill the brief
EXCERPT_CHARS = 900              # opening of each article read for the brief; never published
FRESH_HOURS = 24               # Today's daily sections prefer stories that broke this recently (Heston, 2026-10-19)
REBRIEF_HOURS = 6                # a story is re-summarized when a new side joins, else at most this often
MAX_NEW_PER_SCAN = 5
MAX_NEW_PER_DAY = 30
CLAIMS_EXTRA = {"2026-10-19": (30, 10)}   # one-off (more per day, more per scan), Heston: check the new sections now
# "Decent" fact-check coverage for the proof of concept (Heston's call, 2026-10-19): about 16 to 20 checks a
# day, nearly every politics account. At most $3.10/day, ~$93/month; $4.10/day (~$123/month) with full stories (2026-10-24).
ANTHROPIC_DAILY_USD = 1.10       # two Opus second opinions (~$0.51 each) a day
GEMINI_DAILY_USD = 3.00          # summaries, full stories, checks, and searches past Google's free allowance (Heston 2026-10-24: +$1 for full stories)
# Testing period (Heston, 2026-10-19: "ok with going over cap, since we are testing"). A higher ceiling, not
# none: it still stops a runaway loop. Ends by itself; the caps above apply again from TESTING_UNTIL + 1 day.
TESTING_UNTIL = "2026-10-25"
TESTING_GEMINI_USD, TESTING_ANTHROPIC_USD = 5.00, 2.00
# One-off raises, approved by Heston for a specific date only. Expires by itself.
GEMINI_EXTRA_USD = {"2026-10-19": 8.00}   # one-off, Heston 2026-10-19: new sections, polls, explanations, Texas races; cap $10.00
GEMINI_EXTRA_USD["2026-10-20"] = 3.50   # one-off, Heston 2026-10-20: +$0.50 over the $5.00 testing cap, to check the Texas polls today; cap $5.50
GEMINI_EXTRA_USD["2026-10-30"] = 1.00   # one-off, Heston 2026-10-30 ("run it"): the unpaced budget was gone by 2 am Texas time; cap $4.00
# Bump when the outlet list changes: a story whose outlets changed since its summary is re-summarized once.
ROSTER_VERSION = "2026-10-19b"   # 35 outlets, 15 left / 15 right
GEMINI_FREE_SEARCHES = 150      # Google gives 5,000 free a month across Gemini 3 models; ~150 a day
SEARCH_USD = 0.014               # then $14 per 1,000 searches (ai.google.dev pricing, 2026-10-18), charged to the Gemini cap
TX_NUMBERS_USD = 0.40            # kept for tx_numbers.py out of the same cap (polls checked against releases), Texas edition only
PACE_FROM = "2026-10-31"        # 2026-10-30 was spent unpaced by 2 am Texas time; its one-off $1 is for right away
PACE_START = 0.20               # share of the day's Gemini budget open at midnight UTC; the rest opens hour by hour
CHECK_RESERVE_USD = 0.35        # most one fact-check has cost (tokens plus paid searches), with margin
UNDERCOUNT = 1.7                 # our cost log ran this far under the real bill (2026-10-17)
RECHECK_AFTER_DAYS = 7
DECIDED = ("Holds up", "Missing context", "Doesn't hold up")
# One-off fresh checks, by library key, when a verdict is known to rest on thin evidence. Runs once each.
FORCE_RECHECK = {"ff5e92501774": "court order cited never names the course; look for a filing that does (2026-10-19)"}
# One-off fresh picture picks, by story id, when a stored picture is known to be wrong. Runs once each.
FORCE_REPICK = {"6cbb56e0d0": "LeBron James matched on the first name in \"James Comey's daughter\" (2026-10-28)"}
OPUS_TYPICAL_USD = 0.51          # measured mean per Opus second opinion, 2026-10-17 eval
RESTORE_VERSION = "1"          # bump to re-run the one-time restore of dropped checked splits from the archive
ARCHIVE_DAYS_BACK = [(datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=n)).isoformat() for n in (2, 1, 0)]
CARRY_OVER = 0.80               # same story, same side: an earlier decided claim this close is the same claim, reworded
SAME_CLAIM = 0.93                # embedding similarity at which two wordings are one claim
# A checked claim keeps its verdict when it comes back in other words, unless a detail changed (Heston,
# 2026-10-30). Measured on the 248-claim library that day: no pair reached 0.93; of the 16 pairs at 0.85 to 0.93,
# five were one claim reworded (two had been given different verdicts) and others differed in a detail that
# matters ("third trip" vs "fourth visit", 0.895). So a pair in this band is one claim only if its numbers match in
# code and a yes/no model call finds every detail the same. Asked once per pair (lib["same_claim"]).
MAYBE_SAME = 0.85
# Shadow mode until the model's answers are scored against a person's reading of the same pairs: asked and
# recorded with both sentences (lib["same_claim"]), never used to reuse a verdict while this is False.
SAME_LIVE = False
# One pass over the pairs already in the library (2026-10-30): new claims bring a pair into the band only a few
# times a day, too few to score. Asked once, under the same cap, through same_claim(); tagged "calibration".
SAME_CALIBRATE = "1"
SAME_CALIBRATE_MAX = 40
SAME_PROMPT = """Are these two sentences the same factual claim?

A: {a}
B: {b}

Answer true only if they assert the same facts: the same people or bodies, the same action, the same numbers,
dates, places and amounts. Different wording is fine ("canceled" and "postponed" a deposition is not fine: they
are different actions; "five days" and "5 days" is fine). One that adds a source ("X said that ...") to the
other is the same claim. One that adds, drops or changes any other detail (a person, a number, a place, a
qualifier like "repeatedly" or "all") is a different claim: answer false. When unsure, answer false."""
_NUM_WORDS = {w: str(i) for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve".split())}
_NUM_WORDS.update({w: str(i) for i, w in enumerate("zeroth first second third fourth fifth sixth seventh eighth ninth tenth".split())})


def numbers_in(text):
    """Every number in a claim, words and ordinals as digits ("third" = "3rd" = 3, "1,200" = 1200)."""
    t = text.lower().replace(",", "")
    out = {re.sub(r"(st|nd|rd|th)$", "", n) for n in re.findall(r"\d+(?:\.\d+)?(?:st|nd|rd|th)?", t)}
    return out | {_NUM_WORDS[w] for w in re.findall(r"[a-z]+", t) if w in _NUM_WORDS}
# Covered by one side (Heston, 2026-10-30; never "Blindspot"): a story 4+ outlets on one side covered and none on the
# other, each side measured against its own roster. Measured on the live scan 10-30 (15 left, 5 center, 15 right):
# 2 left-only and 3 right-only stories. Its summaries come out of the day's caps, after Today's sections.
ONE_SIDE_MIN = 4
ONE_SIDE_HOURS = 48         # the story's newest article is at most this old
ONE_SIDE_LANE = 3           # stories per lane
ONE_SIDE_PER_DAY = 6        # new summaries a day for the section (about 6 approved; no cap raised)
ONE_SIDE_PER_SCAN = 2
PICKED_UP_DAYS = 7
# The zero is checked against every article in the 7-day pool, not only the story's own: grouping uses the last
# 48 hours, so on 10-30 Fox News, Daily Wire, OAN and Breitbart's Spain train crash reports (its first day) had aged
# out and the story read "0 right-leaning". Measured that day on 6 stories: other-side reports of the same event
# scored 0.835 to 0.915 against the story's centre; the closest article for a true zero, 0.735 (a photo roundup).
ZERO_SIM = 0.78
ZERO_NEAR = 0.70            # recorded for review (lib one_side.near), not acted on
MIN_OUTLETS_AGREED = 2           # an agreed fact needs at least this many outlets to state it
BRIEF_VERSION = "8"              # bump when the brief instructions change, so cached briefs regenerate
PRICES = {"claude-opus-5-5": (4.00, 20.00, 0.010), "claude-haiku-5-5": (0.10, 0.50, 0), "claude-sonnet-5-5": (2.00, 10.00, 0),
          "gemini-3.8-flash": (0.75, 3.75, 0.0)}   # Gemini searches are tracked by count, not dollars

_item = lambda props, req: {"type": "object", "properties": props, "required": req, "additionalProperties": False}
_ints = {"type": "array", "items": {"type": "integer"}}
SAME_SCHEMA = _item({"same": {"type": "boolean"}}, ["same"])
BRIEF_SCHEMA = _item({
    "common_ground": {"type": "array", "items": _item({"fact": {"type": "string"}, "articles": _ints}, ["fact", "articles"])},
    "agreed": {"type": "array", "items": _item({"fact": {"type": "string"}, "articles": _ints}, ["fact", "articles"])},
    "differences": {"type": "array", "items": _item({
        "point": {"type": "string", "description": "What the coverage differs on, in neutral words."},
        "positions": {"type": "array", "items": _item({
            "says": {"type": "string"}, "articles": _ints,
            "crux": {"type": "string", "description": "Copied word for word from says: the short phrase that is what this side says differently."},
            "checkable_claim": {"type": "string", "description": "A checkable factual claim this side makes, as one statement, attributed. Else empty."},
        }, ["says", "crux", "articles", "checkable_claim"])},
        "checkable_claim": {"type": "string", "description": "Deprecated; leave empty."},
    }, ["point", "positions", "checkable_claim"])},
    "values_questions": {"type": "array", "items": {"type": "string"}},
    "main_subject": _item({"name": {"type": "string", "description": "Full name as commonly written, e.g. 'Ilhan Omar'."},
                           "kind": {"type": "string", "enum": ["person", "organization", "place", "none"]}}, ["name", "kind"]),
}, ["common_ground", "agreed", "differences", "values_questions", "main_subject"])

BRIEF_PROMPT = """You are writing the neutral brief for one news story, from the numbered coverage
below (each line: outlet, its audience lean, headline, its summary when there is one, and the opening
of the article when we could read it).

Write:
- common_ground: 3 to 6 sentences that, read in order, report the story the way a wire service would:
  what happened, who is involved, when and where, what each named party says, and the key numbers.
  Use only facts that at least one left-leaning AND at least one right-leaning outlet both state in
  their own text (headline, summary or opening). Write each sentence at the level of detail both sides
  give, leaving out any number, quote or framing only one side uses. Even when the sides disagree on
  why or how, they usually agree on what happened: that is common ground. Each sentence is one fact
  with every article number that states it. Fewer sentences only if the coverage truly shares less.
  The first sentence is the news itself, standing alone for a reader who knows nothing about the story:
  who did what, and where or when (as a wire story's first line would put it), never a detail, a
  consequence or a follow-up. It is shown alone on the home page.
- agreed: up to 3 more facts, not already in common_ground, that several outlets report. Plain, neutral sentences. Prefer facts reported
  by outlets of different leans. When left- and right-leaning outlets both report the same core event,
  write that fact at the level of detail they share: leave out a number, quote or detail only some of
  them give, or make that detail its own fact. List every article number that states the fact.
- differences: up to 3 points where the coverage differs, especially where left-leaning and
  right-leaning outlets tell it differently (the lean of each outlet is shown in the coverage list): in
  what happened, in a disputed fact, in context left out, or in emphasis. Name the point neutrally, then
  give each position in neutral words with the article numbers that take it, and copy into crux the
  few words of that position that are the actual difference (they will be shown in bold). For each position,
  left and right alike, if it states any fact about the world (what happened, what someone did or said, a
  number), write that claim as one statement in its
  checkable_claim, attributed to whoever made it but never to the outlet (write "A federal judge
  approved the warrant", not "The Daily Wire reports a federal judge approved the warrant"), so each
  side's facts can be checked the same way; otherwise leave it empty.
- values_questions: up to 2 questions about what should happen or what matters more, worded neutrally.
- main_subject: the one person (or organization, or place) the story is mainly about, by full name.
  Use kind "none" if there is no single clear subject.

Rules:
- Attribute every claim to whoever made it. If a person, party, agency or lawyer says something, write
  who says it ("The Justice Department says about 200,000...", "Omar's attorneys say the search was
  unlawful"). Never state a claim someone made as a fact, and never present what an outlet reports
  someone saying as the outlet's own view.
- Agreed facts are what happened: the event itself (who did what, when, where) is almost always
  agreed when several outlets report it, and should be listed. Attribute only claims someone makes
  ("Her attorneys say the search was unlawful"). A disputed or one-sided assertion is a difference.
  Most stories have at least two agreed facts.
- Use only what is in the coverage below. Add nothing from your own knowledge. Do not judge which side
  is right. Do not use loaded words. Use only article numbers from the list.

Claims already checked for this story. If a side's position still rests on one of these, copy it word
for word as that position's checkable_claim, so its check carries over:
{prior}

Coverage:
{coverage}"""

CONFIRM_SCHEMA = _item({"facts": {"type": "array", "items": _item({"fact": {"type": "integer"}, "stated_by": _ints}, ["fact", "stated_by"])}}, ["facts"])
CONFIRM_PROMPT = """For each numbered fact, list which numbered articles state it, using ONLY the text of
those articles below. An article states a fact only if its headline, summary or opening says it; implying
it or being about the same topic is not enough.

Facts:
{facts}

Articles:
{articles}"""

SUPPORT_SCHEMA = _item({"established": {"type": "string", "enum": ["all", "part", "none"]},
                        "missing": {"type": "string", "description": "Only the part of the claim the evidence does not establish, as a short phrase starting with 'that' (e.g. 'that other work was paused'). Empty if all is established."}},
                       ["established", "missing"])
LOADED_VERSION = "2"
IMAGES_VERSION = "6"   # 2: aliases, transliterations, headline fallback; 3: no maps, flags, logos; 4: article pictures, nothing graphic
ALT_VERSION = IMAGES_VERSION + ".3"   # .2: a backup never shares the first picture's surname; .3: on every path
LOADED_SCHEMA = _item({"terms": {"type": "array", "items": _item({
    "term": {"type": "string", "description": "Copied exactly as the outlet wrote it."},
    "articles": _ints,
    "why": {"type": "string", "description": "Why it is loaded, in at most 12 words."},
    "neutral": {"type": "string", "description": "A plainer, neutral way to say it."}},
    ["term", "articles", "why", "neutral"])}}, ["terms"])
LOADED_PROMPT = """Below is the coverage of one news story: each numbered line is an outlet, its audience lean, its
headline, its summary, and the opening of the article when we could read it.

List words or short phrases the OUTLETS THEMSELVES use that are inflammatory or clearly slanted: emotionally
charged labels, insults, scare words, loaded characterizations, partisan labels (for example "regime",
"radical", "slammed", "meltdown", "far-right", "leftist", "illegal aliens", "extremist"). Rules:
- Only the outlet's own words. Skip anything inside quotation marks or attributed to a speaker: quoting
  someone is not the outlet's language.
- Copy each term exactly as written, at most six words.
- Hold left-leaning and right-leaning outlets to the same standard. Up to 4 terms per side; none is fine.
- Ordinary, accurate words are not loaded ("arrested", "said", "Republican").
For each term give every article number that uses it, why it is loaded, and a neutral alternative.

Coverage:
{coverage}"""

AD_VERSION = "3"   # 2: the claims driving the race, not only ads (Heston, 2026-10-19). 3: re-run on the tightened Texas filter
AD_SCHEMA = _item({"claims": {"type": "array", "items": _item({
    "speaker": {"type": "string", "description": "Who made the claim: the campaign, candidate, party or group, by name."},
    "target": {"type": "string", "description": "Who the claim is about, by name. Empty if no one."},
    "kind": {"type": "string", "enum": ["ad", "statement"]},
    "assertion": {"type": "string", "description": "The factual claim itself, as one checkable statement, without 'the ad says'."},
    "articles": _ints}, ["speaker", "target", "kind", "assertion", "articles"])}}, ["claims"])
AD_PROMPT = """Below is this week's coverage of one Texas election race: each numbered line is an outlet, its audience
lean, its headline, its summary, and the opening of the article when we could read it.

List up to 3 factual claims driving this race that the coverage reports someone making: a candidate, campaign,
party, official or political group, in an ad, an attack, a speech or a post, about an opponent, the race, or
voting itself (who can vote, how ballots are counted, fraud). Rules:
- Only claims someone else is reported to have made. Never the outlet's own reporting.
- Only claims of fact that can be checked (a vote, a record, a number, an event, something someone did or
  said), not opinions or slogans.
- Prefer the claims most disputed or most repeated, and give each side the same chance: if both sides made
  checkable claims, include both.
- assertion is the claim itself in plain words, so it can be checked on its own.
For each, give every article number that reports it. None is fine.

Coverage:
{coverage}"""
EXPLAIN_VERSION = "1"
EXPLAIN_PER_SCAN = 20     # explanations written per scan, six at a time
RUN_BUDGET_S = 22 * 60    # after this, a scan starts no new AI work and saves
EXPLAIN_SCHEMA = _item({"part": {"type": "string"}, "context": {"type": "string"}}, ["part", "context"])
# What an explanation line may never do (Heston, 2026-10-20, after two shipped). Checked in code on every new
# line and, every scan, on every line already live, so a line that breaks a rule is rewritten, never left up.
PLEADING = re.compile(r"\b(sounds?|seems?|appears?) (right|true|credible|plausible|believable|reasonable)|\bcredib|\bwhy (it|this|people|some)\b|\bbelievab", re.I)
ABOUT_THE_CHECK = re.compile(r"\b(rated|rating|verdict|classified|labell?ed|deemed|judged)\b[^.]{0,60}\b(unproven|false|misleading|confirmed|"
                             r"holds? up|missing context|doesn'?t hold up|accurate|inaccurate)\b|\bexplain\w* why\b|\b(the|this) (fact-?)?check(er)?\b", re.I)
_FILLER = {"a", "an", "the", "of", "u", "s"}


def explain_problem(line):
    """Why an explanation line can't be shown, or None. Empty is fine: the page leaves that line out."""
    if not line:
        return None
    if PLEADING.search(line):
        return "it argues for the claim"
    if ABOUT_THE_CHECK.search(line):
        return "it talks about the rating or the check instead of the facts"
    m = re.match(r"^(.+?)\s+(?:is|are|was|were)\s+(.+?)[.!]?$", line.strip(), re.I)
    words = lambda t: set(re.findall(r"[a-z0-9']+", t.lower())) - _FILLER
    # A short "X is a Y" whose Y only repeats X: "District Judge Ana C. Reyes is a district judge." Short only, so a
    # real finding that ends in a name ("...declares that the name of the state is New Mexico") still stands.
    if m and len(m[1].split()) <= 6 and words(m[2]) and words(m[2]) <= words(m[1]):
        return "it is true by definition and tells the reader nothing"
    if len(line) > 280:
        return "it is too long"
    return None


def restates(line, claim):
    """True when a line is mostly the claim's own words: "The assertion that Oz will lead the task force is false"
    names nothing false. A False or Misleading line must say which part is wrong (Heston, 2026-10-21)."""
    stop = {"the", "a", "an", "that", "is", "was", "are", "of", "to", "in", "on", "and", "it", "this", "claim", "assertion",
            "statement", "false", "not", "true", "will", "be", "has", "have", "by", "for", "with", "as"}
    w = lambda t: [x for x in re.findall(r"[a-z0-9']+", (t or "").lower()) if x not in stop]
    mine, theirs = w(line), set(w(claim))
    return bool(mine) and sum(x in theirs for x in mine) / len(mine) >= 0.8


def line_problem(c, field, line):
    """explain_problem, plus: a False or Misleading 'part' line must not just repeat the claim."""
    why = explain_problem(line)
    if not why and field == "part" and line and c.get("verdict") in ("Doesn't hold up", "Missing context") and restates(line, c.get("claim", "")):
        why = "it repeats the claim instead of saying which part is false or what is missing"
    return why


def explain_ok(c):
    x = c.get("explain") or {}
    return not line_problem(c, "part", x.get("part")) and not line_problem(c, "context", x.get("context"))
EXPLAIN_ASK = {  # what each line says, by verdict
    "Holds up": ("what in the claim the sources confirm", "leave empty"),
    "Missing context": ("the part of the claim that is true", "what the claim leaves out that changes the picture"),
    "Doesn't hold up": ("exactly which part of the claim is false, in your own words, never the claim restated", "what the sources show instead"),
    "Unproven": ("the part of the claim the sources do establish, or empty if none", "what the sources could not establish"),
}
EXPLAIN_PROMPT = """A fact-checker has checked this claim. Explain its verdict to a reader in two short, plain lines, using only
facts in the checker's finding. No opinion, no judgment of anyone's motives, no "the claim" or "the statement".
Never say why the claim sounds right, believable or credible, and never argue for it: only what the sources show.
Never mention the verdict, the rating, the check or the checker, and never say what the sources fail to explain
about a rating: the reader wants the facts, not our process. Each line must say something specific about the
claim's subject that a reader could not know without the sources, never something true by definition ("Judge
Reyes is a judge").

Claim: {claim}
Verdict: {verdict}
The checker's finding: {finding}

part (at most 25 words): {part}
context (at most 30 words): {context}"""
# The full story (Heston, 2026-10-24: readers ask "I want to read the whole story"). Written only from what the
# brief already holds: facts both sides report (stated plainly), facts one side reports (always attributed to
# their outlets), the splits (each version with its outlets) and our checks. Every sentence lists the material
# it uses, and code holds it to that material: names and numbers must be in it, one-side material must name an
# outlet, none of the story's loaded words, nothing that argues. A failing sentence is dropped; under three
# sentences, no full story. Rewritten when the brief changes or a check on the story is decided.
FULL_VERSION = "1"
FULL_SCHEMA = _item({"paragraphs": {"type": "array", "items": _item({"sentences": {"type": "array", "items": _item({
    "text": {"type": "string"}, "sources": {"type": "array", "items": {"type": "string"}}}, ["text", "sources"])}}, ["sentences"])}},
    ["paragraphs"])
FULL_PROMPT = """Write the full story of this news event for a reader who wants all of it, the way a neutral wire-service
reporter would, using ONLY the numbered material below. Rules:
- Open with what outlets on both the left and the right report (marked BOTH), stated plainly, most important first.
- Anything not marked BOTH must say who reports it, by outlet name ("Fox News and the New York Post report that ...").
- Where coverage differs, give each version with its outlets, in the same neutral words. If fACTUAL checked it, say what
  the check found, in plain words ("fACTUAL's check found this false: ...").
- Some material describes how outlets frame or emphasize the story rather than a fact. Write it as those outlets' own
  framing ("The Daily Mail and the New York Post frame the charges as ..."), never as outlets reporting what other
  outlets do ("X reports that right-leaning outlets frame ...").
- No opinion, no judgment of anyone's motives, no words that take a side, and never these words: {loaded}.
- Never add a fact, name, number, date or quotation that is not in the material.
- 3 to 6 short paragraphs of 2 to 4 sentences. For every sentence, list the ids of the material it uses (F1, P1a, ...).

Material:
{material}"""
SHOWN_VERDICT = {"Holds up": "confirmed", "Missing context": "misleading", "Doesn't hold up": "false", "Unproven": "unproven"}
SIDE_WORDS = re.compile(r"\b(left|right)-leaning\b|\bcenter outlets?\b", re.I)
TAKES_SIDES = re.compile(r"\b(clearly|obviously|shocking\w*|outrage\w*|disgrace\w*|so-called|slammed|blasted|radical|extremist|"
                         r"far-left|far-right|smear\w*|unfortunately|fortunately|rightly|wrongly)\b", re.I)
FULL_STARTS = {"according", "the", "a", "an", "in", "on", "at", "after", "before", "both", "outlets", "coverage", "it", "they",
               "he", "she", "his", "her", "their", "this", "that", "these", "those", "while", "whether", "some", "other", "others",
               "also", "however", "but", "and", "as", "when", "since", "for", "by", "of", "factual", "factual's", "left-leaning",
               "right-leaning", "center", "neither", "no", "none", "until", "during", "with", "what", "which", "who"}


def full_material(brief, claims):
    """The numbered material for the full story, and per id: its text and its outlets (None when both sides)."""
    lines, src = [], {}
    for i, f in enumerate(brief.get("agreed", []), 1):
        both = "left" in f["sides"] and "right" in f["sides"]
        k = f"F{i}"
        src[k] = {"text": f["fact"], "outlets": None if both else list(f.get("reported_by", []))}
        lines.append(f"{k} [{'BOTH' if both else 'reported by ' + ', '.join(f.get('reported_by', []))}] {f['fact']}")
    for di, d in enumerate(brief.get("differences", []), 1):
        lines.append(f"D{di} where coverage differs: {d.get('point', '')}")
        for pi, pos in enumerate(d.get("positions", [])):
            k = f"P{di}{chr(97 + pi)}"
            c = claims.get(pos.get("check")) if pos.get("check") else None
            check = ""
            if c and c.get("verdict") in SHOWN_VERDICT and (c.get("finding") or "").strip():
                x = c.get("explain") or {}
                check = f" | fACTUAL checked '{c['claim']}': {SHOWN_VERDICT[c['verdict']]}. " + " ".join(t for t in (x.get("part"), x.get("context")) if t)
            text = f"{pos.get('says', '')}{check}"
            src[k] = {"text": text, "outlets": list(pos.get("outlets", []))}
            lines.append(f"  {k} [reported by {', '.join(pos.get('outlets', []))}] {text}")
    return "\n".join(lines), src


def full_sentence_problem(text, ids, src, loaded):
    """Why a full-story sentence can't be used, or None."""
    used = [src[i] for i in ids if i in src]
    if not used or len(used) != len(ids):
        return "it cites no material, or material that doesn't exist"
    if len(text.split()) > 45:
        return "too long"
    pool = " ".join(u["text"] for u in used) + " " + " ".join(o for u in used for o in (u["outlets"] or []))
    low = pool.casefold()
    for n in re.findall(r"\d[\d,.]*", text):
        if n.rstrip(".,") not in pool:
            return f"number {n} is not in its material"
    for j, w in enumerate(text.split()):
        w = re.sub(r"[^\w'\u2019.-]", "", w).rstrip(".")
        base = w.casefold().replace("\u2019", "'").split("'s")[0]
        if w[:1].isupper() and base not in low and not (j == 0 and base in FULL_STARTS) and base not in FULL_STARTS:
            return f"name {w} is not in its material"
    for u in used:  # one-side material names its outlets (or the side)
        if u["outlets"] and not any(o.casefold() in text.casefold() for o in u["outlets"]) and not SIDE_WORDS.search(text):
            return "one side's material without saying who reports it"
    for t in loaded:
        if t and t.casefold() in text.casefold():
            return f"uses the loaded term '{t}'"
    if TAKES_SIDES.search(text) or PLEADING.search(text):
        return "takes a side or argues"
    if re.search(r"\breports? that\b[^.]*\b(outlets|coverage)\b", text, re.I):
        return "has outlets reporting what other outlets do"
    return None


POLL_VERSION = "1"
POLL_SCHEMA = _item({"polls": {"type": "array", "items": _item({
    "question": {"type": "string", "description": "The question as a reader would answer it, neutral, at most 25 words."},
    "options": {"type": "array", "items": {"type": "string"}, "description": "2 to 4 answers, each at most 12 words."}},
    ["question", "options"])}}, ["polls"])
POLL_PROMPT = """Turn each question below into a poll for readers of a news story. For each, write:
- question: the same question, worded so a reader can pick one answer. Keep its meaning. Neutral words.
- options: 2 to 4 answers that are mutually exclusive, that together cover the main positions people across
  the political spectrum actually hold, and that are worded with equal care, length and respect. No answer
  may lead, mock or sound more reasonable than another by its wording. Don't add "Not sure": we add it.

Story: {title}

Questions:
{questions}"""
IMAGE_TITLES_SCHEMA = _item({"titles": {"type": "array", "items": {"type": "string"}}}, ["titles"])
IMAGE_TITLES_PROMPT = """Suggest up to 3 exact English Wikipedia article titles whose main picture would illustrate this news
story for a general reader, best first. Prefer the specific thing the story is about: a virus or other
cause of disease, a building, an institution, a product, a vehicle, a landmark at the place, a named event.
Avoid articles whose main picture would likely show sick, injured or dead people, violence or weapons in
use, or anything graphic. Avoid maps and flags. Use titles exactly as they appear on Wikipedia.

Story: {story}"""

FITS_SCHEMA = _item({"fits": {"type": "boolean"}, "why": {"type": "string"}}, ["fits", "why"])
FITS_PROMPT = """A news site wants to show this picture next to this story. Using the picture's own description,
answer whether it makes sense there for a reader: it shows the thing, place, institution or kind of event
the story is about, and it would not mislead (a different country, a different event, a different person,
an unrelated object that shares a name). A generic picture of the right thing is fine; a picture from
somewhere else that could be mistaken for this story is not. Anything graphic is not.

Story: {story}
Picture: {subject}. Description: {about}"""

CLAIM_SCHEMA = _item({"claim": {"type": "string", "description": "One checkable factual claim, or empty."}}, ["claim"])
CLAIM_PROMPT = """One side of a news story's coverage is summarized below. Write the single most important factual
claim this account makes, as one plain statement that can be checked against primary sources (court
records, official statements, government data, documents). Attribute it to whoever made it ("Police said
Oliver was charged with ...", "Trump said ..."), but never to a news outlet. Use only what the account
says; add nothing. If the account makes no factual claim, only emphasis, framing or opinion, return an
empty claim.

The point the coverage differs on: {point}
This side's account: {says}"""

SUPPORT_VERSION = "4"   # 2: quotes judged in their page passage; 3: plus the page's sentences naming the claim's terms, editor's standard
SUPPORT_PROMPT = """Below is a claim and the evidence for it. Each item is a quote copied word for word from its
source page, shown with the page's address and the passage around the quote on that page, which our
code read itself, and other sentences from the same page that mention names or numbers in the claim.
Using ONLY this evidence, not anything you know, decide whether it establishes every part of the claim.
The address, passage and other sentences can establish what a quote is about (which court, case, place,
person or date). Judge as a careful editor would: ordinary paraphrase and plain implication count (2,700
events are thousands of events; events that took place were planned; the same place, person or body under
a slightly different name is the same). Words that change the meaning do
not: a quote saying someone left or was asked to reconsider does not establish that they were fired; a
total does not establish a record; an endorsement does not establish when it was withheld.

Answer "all" only if every part of the claim, as worded, is established. Answer "part" if some of it is
and some is not, and in "missing" name only the part that is not established, briefly. Answer "none" if the evidence does not support it.

Claim: {claim}

Evidence:
{quotes}"""


def cost_usd(model, usage, searches=0):
    p = next((v for k, v in PRICES.items() if model and model.startswith(k)), (4.0, 20.0, 0.01))
    u = usage or {}
    tin = u.get("input_tokens", 0) + 1.25 * u.get("cache_creation_input_tokens", 0) + 0.1 * u.get("cache_read_input_tokens", 0)
    return (tin * p[0] + u.get("output_tokens", 0) * p[1]) / 1e6 + searches * p[2]


def load_library():
    """Last scan's library from the live site. Only a 404 means 'start empty'; any other failure
    means skip this scan, so a network blip can never trigger a full, paid re-check."""
    try:
        with urllib.request.urlopen(urllib.request.Request(LIBRARY_URL, headers={"User-Agent": C.UA}), timeout=20, context=C.SSL_CTX) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"claims": {}, "spend": {}}
        raise


def key_of(text):
    return hashlib.sha1(re.sub(r"[^a-z0-9%$.]+", " ", text.lower()).strip().encode()).hexdigest()[:12]


THOUGHTS = {"tokens": 0, "calls": 0}   # thinking tokens this scan, logged so effort can be tuned on data
# Every refused AI call this scan (billing, quota, server), saved in the library as ai_errors, so a run-out
# balance shows the same hour (Heston's Gemini credit hit -$0.05 on 2026-10-24 and we couldn't see it).
AI_ERRORS = []


def note_ai_error(where, e):
    body = ""
    if isinstance(e, urllib.error.HTTPError):
        try:
            body = e.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
    AI_ERRORS.append({"where": where, "error": f"{type(e).__name__}: {e} {body}".strip()[:300]})


def gemini_json(prompt, schema, thinking=None):
    """thinking: None keeps the model default (medium on gemini-3.8-flash); "low" for pure matching tasks."""
    key = os.environ["GEMINI_API_KEY"]
    req_body = {"model": C.GEMINI_MODEL, "input": prompt,
                "response_format": {"type": "text", "mime_type": "application/json", "schema": schema}}
    if thinking:
        req_body["generation_config"] = {"thinking_level": thinking}
    body = json.dumps(req_body).encode()
    req = urllib.request.Request(C.GEMINI_URL, data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=120, context=C.SSL_CTX) as r:
            raw = json.loads(r.read())
    except Exception as e:
        note_ai_error("gemini", e)
        raise
    texts = []
    C._walk(raw.get("steps", raw), lambda n: texts.append(n["text"]) if isinstance(n, dict) and n.get("type") == "text" and isinstance(n.get("text"), str) else None)
    u = raw.get("usage") or {}
    THOUGHTS["tokens"] += u.get("thought_tokens") or u.get("total_thought_tokens") or 0
    THOUGHTS["calls"] += 1
    usage = {"input_tokens": u.get("input_tokens") or u.get("total_input_tokens") or 0,
             "output_tokens": (u.get("output_tokens") or u.get("total_output_tokens") or 0) + (u.get("thought_tokens") or u.get("total_thought_tokens") or 0)}
    return json.loads(raw.get("output_text") or texts[-1]), usage


def sourced_finding(r):
    """Drop any sentence whose numbers are not in a verified quote."""
    bad = set(r.get("numbers_unsourced") or [])
    if not bad:
        return r["output"].get("finding", ""), 0
    sentences = re.split(r"(?<=[.!?])\s+", r["output"].get("finding", ""))
    keep = [s for s in sentences if not (set(C.numbers_in(s)) & bad)]
    return " ".join(keep), len(sentences) - len(keep)


def public_record(claim, first, second, verdict, note, story_ids, said_by):
    """What readers see about one checked claim. Only verified evidence is published."""
    finding, dropped = sourced_finding(first)
    fields = ("url", "publisher", "published", "quote", "role")
    ev = [{k: e[k] for k in fields} for e in first["evidence_checked"] if e["verified"]]
    if second and second.get("evidence_checked"):
        seen = {x["url"] for x in ev}
        ev += [{k: e[k] for k in fields} for e in second["evidence_checked"] if e["verified"] and e["url"] not in seen]
    out = first["output"]
    return {
        "claim": claim, "verdict": verdict, "steelman": out.get("steelman", ""), "finding": finding,
        "sentences_dropped": dropped, "reasoning_flags": out.get("reasoning_flags", []), "newest_data": out.get("newest_data", ""),
        "evidence": ev, "figures": first.get("figures", []), "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "checked_by": first["model"], "second_opinion": (second or {}).get("model"), "second_verdict": (second or {}).get("verdict"),
        "note": note, "stories": story_ids, "said_by": said_by,
        "model_verdict": first["verdict_raw"], "pending_second": note == "second opinion waiting for budget",
    }


def main():
    C.load_env()
    if not (os.environ.get("GEMINI_API_KEY") and os.environ.get("ANTHROPIC_API_KEY")):
        print("check_today: API keys not set; skipping")
        return 0
    stories_path = ROOT / "data/stories.json"
    data = json.loads(stories_path.read_text())
    summaries = {}
    if (ROOT / "data/articles.json").exists():
        summaries = {a["url"]: a.get("summary", "") for a in json.loads((ROOT / "data/articles.json").read_text())["articles"]}
    side_of = {f["source"]: f.get("side", "unplaced") for f in data.get("feeds", [])}
    try:
        lib = load_library()
    except Exception as e:
        print(f"check_today: could not read the library ({e}); skipping this scan")
        return 0

    today = datetime.now(timezone.utc).date().isoformat()
    spend = lib.setdefault("spend", {}).setdefault(today, {"anthropic_usd": 0.0, "gemini_usd": 0.0, "gemini_searches": 0, "new_claims": 0})
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
    lib["spend"] = {d: v for d, v in lib["spend"].items() if d >= cutoff}
    claims = lib.setdefault("claims", {})
    briefs = lib.setdefault("briefs", {})
    images = lib.setdefault("images", {})
    if lib.get("images_v") != IMAGES_VERSION:  # the matcher improved: retry names that found no image before
        # retry misses, and re-judge saved place and organization pictures (a map is not a photo)
        images = lib["images"] = {k: v for k, v in images.items() if v and k.startswith("person:")}
        lib["images_v"] = IMAGES_VERSION
    lib.pop("extractions", None)  # replaced by briefs

    testing = today <= TESTING_UNTIL
    gemini_cap = max(GEMINI_DAILY_USD + GEMINI_EXTRA_USD.get(today, 0.0), TESTING_GEMINI_USD if testing else 0.0)
    anthropic_cap = TESTING_ANTHROPIC_USD if testing else ANTHROPIC_DAILY_USD
    more_day, more_scan = CLAIMS_EXTRA.get(today, (0, 0))
    new_per_day, new_per_scan = MAX_NEW_PER_DAY + more_day, MAX_NEW_PER_SCAN + more_scan

    # A scan has RUN_BUDGET_S to start new AI work; after that it only saves what it has, so GitHub's time limit
    # can never kill it before the library (and the day's spend) is written. 2026-10-19: four scans in a row ran
    # past 30 minutes and were killed unsaved.
    started = time.monotonic()
    past_deadline = lambda: time.monotonic() - started > RUN_BUDGET_S

    # While the Texas edition runs, the race numbers step (tx_numbers.py, after this one) keeps a little of the
    # day's cap for confirming new polls against their releases; claims stop that much short of the cap.
    tx = (data.get("regions") or {}).get("tx")
    work_cap = gemini_cap - (TX_NUMBERS_USD if tx and datetime.now(timezone.utc) < datetime.fromisoformat(tx["until"]) else 0.0)
    # The day's budget is paced across the day: a fifth at midnight UTC, the rest in step with the clock. Unpaced,
    # the first three scans after midnight UTC (7 pm in Texas) spent it all and Today froze until the next evening
    # (Heston, 2026-10-30: "nothing has updated in like 16 hours"). Same total; what a scan leaves, the next can use.
    now = datetime.now(timezone.utc)
    if today >= PACE_FROM:
        work_cap *= min(1.0, PACE_START + (1 - PACE_START) * (now.hour + now.minute / 60) / 24)

    def gemini_ok():
        return spend["gemini_usd"] < work_cap and not past_deadline()

    def charge_gemini(usage, searches=0):
        paid = max(0, spend["gemini_searches"] + searches - GEMINI_FREE_SEARCHES) - max(0, spend["gemini_searches"] - GEMINI_FREE_SEARCHES)
        spend["gemini_usd"] = round(spend["gemini_usd"] + UNDERCOUNT * cost_usd(C.GEMINI_MODEL, usage) + paid * SEARCH_USD, 4)
        spend["gemini_searches"] += searches

    def charge_anthropic(model, usage, searches=0):
        spend["anthropic_usd"] = round(spend["anthropic_usd"] + UNDERCOUNT * cost_usd(model, usage, searches), 4)

    def charge_pipe():
        for u in C.PIPE_USAGE:
            charge_anthropic(u["model"], u)
        C.PIPE_USAGE.clear()

    from fastembed import TextEmbedding
    embed = TextEmbedding("BAAI/bge-small-en-v1.5")
    vec = lambda texts: (lambda a: a / np.linalg.norm(a, axis=1, keepdims=True))(np.array(list(embed.embed(texts)), dtype=np.float32))
    lib_keys = list(claims)
    lib_vecs = vec([claims[k]["claim"] for k in lib_keys]) if lib_keys else None

    same_cache = lib.setdefault("same_claim", {})

    def same_claim(text, k):
        """A reworded claim in the 0.85-0.93 band: numbers equal in code, then every detail the same (model)."""
        if numbers_in(text) != numbers_in(claims[k]["claim"]):
            return False
        pair = f"{key_of(text)}:{k}"
        if pair not in same_cache or not isinstance(same_cache[pair], dict):
            if spend["gemini_usd"] >= work_cap:
                return False  # not asked: checked as a new claim, under the same caps as always
            try:
                out, usage = gemini_json(SAME_PROMPT.replace("{a}", claims[k]["claim"]).replace("{b}", text), SAME_SCHEMA, thinking="low")
            except Exception as e:
                note_ai_error("same_claim", e)
                return False
            charge_gemini(usage)
            same_cache[pair] = {"same": bool(out["same"]), "a": claims[k]["claim"], "b": text,
                                "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            print(f"  same claim? {out['same']}: {text[:60]} | {claims[k]['claim'][:60]}")
        return SAME_LIVE and same_cache[pair]["same"]

    def find_existing(text):
        k = key_of(text)
        if k in claims:
            return k
        if lib_vecs is not None:
            s = lib_vecs @ vec([text])[0]
            i = int(np.argmax(s))
            if s[i] >= SAME_CLAIM:
                return lib_keys[i]
            for i in [j for j in np.argsort(-s)[:3] if s[j] >= MAYBE_SAME]:
                if lib_keys[i] in claims and same_claim(text, lib_keys[i]):
                    return lib_keys[i]
        return None

    if lib.get("same_calibrated") != SAME_CALIBRATE and lib_vecs is not None and gemini_ok():
        sims = np.triu(lib_vecs @ lib_vecs.T, 1)
        band = sorted(zip(*np.where((sims >= MAYBE_SAME) & (sims < SAME_CLAIM))), key=lambda ij: -sims[ij])[:SAME_CALIBRATE_MAX]
        before = set(same_cache)
        for i, j in band:
            same_claim(claims[lib_keys[j]]["claim"], lib_keys[i])
        for pair in set(same_cache) - before:
            same_cache[pair]["calibration"] = True
        gated = [f"{key_of(claims[lib_keys[j]]['claim'])}:{lib_keys[i]}" for i, j in band
                 if numbers_in(claims[lib_keys[j]]["claim"]) == numbers_in(claims[lib_keys[i]]["claim"])]
        if all(p in same_cache for p in gated):  # a pair not asked (cap reached) is tried next scan
            lib["same_calibrated"] = SAME_CALIBRATE
        print(f"  same claim calibration: {len(band)} library pairs in the band, {len(set(same_cache) - before)} asked")

    def support_ok(record):
        """Holds up must follow from the verified quotes, read in their passage on the source page."""
        # Version 1 judged quotes alone and cut true claims whose quotes didn't repeat the names (a court
        # order's excerpt doesn't name the judge). Re-judge those, starting again from the checker's verdict.
        if record.get("support") == "partial" and record.get("support_v") != SUPPORT_VERSION and record.get("model_verdict") == C.HU \
                and not record.get("second_opinion"):
            record["verdict"] = C.HU
            record["change_why"] = "Its quotes were read again in their source pages, and they support the claim as stated."
            record.pop("support", None)
            if (record.get("note") or "").startswith("the sources confirm part"):
                record["note"] = None
        if record["verdict"] != C.HU or "support" in record or spend["gemini_usd"] >= gemini_cap + 0.10:
            return
        items = []
        for e in record["evidence"]:
            if e.get("role") not in ("supports", "context"):
                continue
            ctx = passage(e["url"], e["quote"])
            more = mentions(e["url"], record["claim"], ctx or e["quote"])
            items.append(f"- Quote: \"{e['quote']}\"\n  Source: {e['publisher']}, {e['url']}"
                         + (f"\n  Passage on the page: \"{ctx}\"" if ctx else "")
                         + "".join(f"\n  Elsewhere on the page: \"{m}\"" for m in more))
        charge_pipe()
        quotes = "\n".join(items)
        if quotes:
            try:
                out, usage = gemini_json(SUPPORT_PROMPT.replace("{claim}", record["claim"]).replace("{quotes}", quotes), SUPPORT_SCHEMA)
            except Exception as e:
                print(f"  support check failed: {e}")
                return
            charge_gemini(usage)
            ok, missing = out["established"] == "all", out.get("missing", "")
        else:
            ok, missing = False, "no verified quote supports it"
        record["support"] = "all" if ok else "partial"
        record["support_v"] = SUPPORT_VERSION
        if not ok:
            if record["verdict"] != C.UN:
                record["change_why"] = "Its quotes were read in their source pages, and they support only part of the claim."
            record["verdict"] = C.UN
            record["note"] = f"the sources confirm part of this claim, not all of it as stated: {missing}".rstrip(": ")

    for rec in claims.values():  # claims checked before the support check existed
        support_ok(rec)

    state = {"new_this_scan": 0}

    def check_claim(text, story_sid, said_by):
        """Library first; a new claim is checked under the caps. Returns the library key or None."""
        existing = find_existing(text)
        rec = claims.get(existing) if existing else None
        fresh = rec and datetime.fromisoformat(rec["checked_at"]) > datetime.now(timezone.utc) - timedelta(days=RECHECK_AFTER_DAYS)
        forced = existing in FORCE_RECHECK and not (rec or {}).get("rechecked")
        if rec and fresh and not rec.get("pending_second") and not forced:
            rec["stories"] = sorted(set(rec.get("stories", [])) | {story_sid})
            return existing
        # Searches past Google's free allowance are paid, and charged to the Gemini cap (charge_gemini).
        # Start a check only with room for a worst-case one: the cap is checked before a check, but its
        # paid searches are charged after, and one overran the cap by $0.45 on 2026-10-19.
        if past_deadline() or state["new_this_scan"] >= new_per_scan or spend["new_claims"] >= new_per_day \
                or spend["gemini_usd"] + CHECK_RESERVE_USD > work_cap:
            return existing
        try:
            first = C.check(text, "gemini")
        except Exception as e:
            print(f"  check failed: {text[:60]}: {e}")
            note_ai_error("check", e)
            return existing
        charge_pipe()
        charge_gemini(first["usage"], first.get("web_searches", 0))
        spend["new_claims"] += 1
        state["new_this_scan"] += 1
        first.pop("trace", None)
        second, note, verdict = None, None, first["verdict"]
        if verdict == C.DHU:
            if anthropic_cap - spend["anthropic_usd"] >= OPUS_TYPICAL_USD:
                try:
                    second = C.check(text, "claude")
                    second.pop("trace", None)
                    charge_anthropic(second["model"], second["usage"], second.get("web_searches", 0))
                    charge_pipe()
                    verdict, note = C.combine(first, second)
                except Exception as e:
                    verdict, note = C.UN, f"second opinion failed: {str(e)[:120]}"
            else:
                verdict, note = C.UN, "second opinion waiting for budget"
        k = existing or key_of(text)
        record = public_record(text, first, second, verdict, note, sorted(set((rec or {}).get("stories", [])) | {story_sid}), said_by)
        if forced:
            record["rechecked"] = FORCE_RECHECK[existing]
        if rec:  # why it was checked again, for the corrections log if the verdict changes (track_changes)
            record["change_why"] = (f"Checked again because {FORCE_RECHECK[existing]}." if forced
                                    else "The second opinion it was waiting for came in." if rec.get("pending_second")
                                    else f"Checked again after {RECHECK_AFTER_DAYS} days, against the newest sources.")
        support_ok(record)
        if forced and record["verdict"] in DECIDED and not record["finding"].strip():
            record["verdict"], record["note"] = C.UN, "no part of the finding could be tied to a verified quote"
        claims[k] = record
        print(f"  {record['verdict']:<16} {text[:80]}")
        return k

    # A verdict never goes out without its reason (Heston, 2026-10-21: a False claim showed no why). The number
    # check (sourced_finding) can drop every sentence of a finding; such a claim is checked once more. If the
    # second finding is emptied too, it is published as Unproven: we could not tie the reason to verified quotes.
    for k, c in claims.items():
        if c.get("verdict") in DECIDED and not (c.get("finding") or "").strip() and not c.get("rechecked"):
            FORCE_RECHECK[k] = "its finding was emptied by the number check, and a verdict needs its reason"
    # One-off fresh checks run on their own: a claim already attached to a story is never asked for again.
    for k, why in FORCE_RECHECK.items():
        rec = claims.get(k)
        if rec and not rec.get("rechecked"):
            print(f"  recheck {k}: {why}")
            check_claim(rec["claim"], (rec.get("stories") or ["recheck"])[0], rec.get("said_by", []))

    def fits(story, brief, rec, key):
        """Portraits are exact name matches; any other picture must also pass the relevance check, once per
        story and picture, before it is shown."""
        if not rec:
            return False
        if key.startswith("person:"):
            return True
        seen = brief.setdefault("image_fits", {})
        if key not in seen:
            if not gemini_ok():
                return False
            facts = " ".join(f["fact"] for f in brief["agreed"] if "left" in f["sides"] and "right" in f["sides"])
            try:
                out, usage = gemini_json(FITS_PROMPT.replace("{story}", f"{story['working_title']}. {facts}"[:1200])
                                         .replace("{subject}", rec["subject"]).replace("{about}", rec.get("about", "")[:500]), FITS_SCHEMA, "low")
                charge_gemini(usage)
                seen[key] = bool(out.get("fits"))
                print(f"  picture {'fits' if seen[key] else 'rejected'}: {rec['subject']} ({(out.get('why') or '')[:80]})")
            except Exception as e:
                print(f"  picture check failed: {e}")
                return False
        return seen[key]

    def person(name):
        """A verified portrait for a full name, looked up once and cached (a miss is cached as None)."""
        ikey = f"person:{name.casefold()}"
        if ikey not in images:
            try:
                images[ikey] = image_for(name, "person")
            except Exception as e:
                print(f"  image lookup failed for {name}: {e}")
                return None
        return images.get(ikey)

    def find_image(story, brief, avoid=frozenset()):
        """The story's picture, best first, skipping any subject in avoid (so a second call finds a different
        one): the main subject, a verified person named in the headline, the headline's actor from the shared
        facts, a Wikipedia article's picture, then any person the facts name."""
        # A backup picture never goes to someone who shares the first picture's surname (Melania Trump on a
        # Donald Trump story, 2026-10-19); a surname alone names someone only when no one else cached shares it.
        # Checked in ok(), which every path uses: .2 checked only two paths, and the main subject path still
        # picked Melania for the women's health story she led.
        avoid_last = {a.split()[-1] for a in avoid}
        ok = lambda rec: bool(rec) and rec.get("subject") not in avoid and (rec.get("subject") or "?").split()[-1] not in avoid_last
        last_count = Counter(r["subject"].split()[-1] for k, r in images.items() if k.startswith("person:") and r)
        subj = brief.get("main_subject") or {}
        if subj.get("name") and subj.get("kind") in ("person", "organization", "place"):
            ikey = f"{subj['kind']}:{subj['name'].casefold()}"
            if ikey not in images:
                try:
                    images[ikey] = image_for(subj["name"], subj["kind"])  # None is cached too: no safe image
                except Exception as e:
                    print(f"  image lookup failed for {subj['name']}: {e}")
            if ok(images.get(ikey)) and fits(story, brief, images[ikey], ikey):
                return images[ikey]
        # The subject has no usable photo (a golf course, say): a person named in the headline, but only one
        # already matched and verified, by full name or a surname of five letters or more, as a whole word.
        # A surname alone never counts when the story uses that word as a first name: the facts are in sentence
        # case, so a capital after it marks a name ("James Comey's daughter" put LeBron James on the story, 2026-10-28).
        title = story["working_title"]
        facts_text = " ".join(f["fact"] for f in brief["agreed"] if "left" in f["sides"] and "right" in f["sides"])
        first_name = lambda w: re.search(rf"\b{re.escape(w)}\s+[A-Z]", facts_text)
        for k, rec in images.items():
            if not (k.startswith("person:") and ok(rec)):
                continue
            full = rec["subject"]
            last = full.split()[-1]
            if last in avoid_last:
                continue
            if re.search(rf"\b{re.escape(full)}\b", title) or (len(last) >= 5 and last_count[last] == 1 and not first_name(last)
                                                               and re.search(rf"\b{re.escape(last)}\b", title)):
                return rec
        # The headline's actor: a full name from the shared facts whose surname is in the headline ("Trump
        # Says ..." -> Donald Trump). Heston: a person the headline is about beats a picture of the place.
        for name in person_names(facts_text)[:6]:
            last = name.split()[-1]
            if last not in avoid_last and len(last) >= 4 and re.search(rf"\b{re.escape(last)}\b", title) and ok(person(name)):
                return person(name)
        if brief.get("img_v") != IMAGES_VERSION and gemini_ok():
            # Ask once which Wikipedia articles' main pictures would illustrate the story (for an Ebola story,
            # "Ebola virus": the virus, not a patient). Each title must exist, and its picture passes the same
            # rules: freely licensed, not a map, flag or logo, nothing graphic.
            brief["img_v"] = IMAGES_VERSION
            try:
                out, usage = gemini_json(IMAGE_TITLES_PROMPT.replace("{story}", f"{title}. {facts_text}"[:1500]), IMAGE_TITLES_SCHEMA, "low")
                charge_gemini(usage)
                brief["image_titles"] = [t.strip() for t in out.get("titles", [])[:3] if t.strip()]
            except Exception as e:
                print(f"  image title suggestion failed: {e}")
        for t in brief.get("image_titles", []):
            ikey = f"title:{t.casefold()}"
            if ikey not in images:
                try:
                    images[ikey] = image_for_title(t)
                except Exception as e:
                    print(f"  image lookup failed for {t}: {e}")
                    continue
            if ok(images.get(ikey)) and fits(story, brief, images[ikey], ikey):
                return images[ikey]
        # Any person the shared facts or the headline name, in order, under the same strict rules. Facts first:
        # they are in sentence case, so capitalized runs are names; headlines are in title case.
        text = " ".join([f["fact"] for f in brief["agreed"] if "left" in f["sides"] and "right" in f["sides"]][:3] + [title])
        for name in person_names(text)[:6]:
            if name.split()[-1] not in avoid_last and ok(person(name)):
                return person(name)
        return None

    def process(story, rebrief=True):
        """Summarize one story (cached unless stale), check its claims, find its image. True if summarized."""
        arts = pick_articles(story["articles"], side_of, ARTICLES_PER_BRIEF)
        outlets_now = sorted({a["source"] for a in story["articles"]})
        sides_now = sorted({side_of.get(o, "unplaced") for o in outlets_now})
        cached = briefs.get(story["sid"])
        age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(cached["at"])).total_seconds() / 3600 if cached else 0
        # Re-summarize on a new brief version, or when the outlets changed and either a new side joined or
        # REBRIEF_HOURS have passed. A new article from an outlet already in the story never triggers it.
        stale = not cached or cached.get("version") != BRIEF_VERSION or (
            cached.get("outlets") != outlets_now and (cached.get("sides") != sides_now or age_h >= REBRIEF_HOURS
                                                      or cached.get("roster") != ROSTER_VERSION))
        brief = cached["brief"] if cached else None
        if stale and rebrief and gemini_ok():
            lines, excerpts = coverage_lines(arts, side_of, summaries)
            try:
                prior = [c["claim"] for c in claims.values() if story["sid"] in c.get("stories", []) and c.get("verdict") in DECIDED]
                raw, usage = gemini_json(BRIEF_PROMPT.replace("{prior}", "\n".join(f"- {t}" for t in prior[:12]) or "(none)")
                                         .replace("{coverage}", "\n".join(lines)), BRIEF_SCHEMA)
                charge_gemini(usage)
                brief = build_brief(raw, arts, lines, side_of, gemini_json, charge_gemini)
                brief = keep_checked_splits(brief, cached["brief"] if cached else None, claims, vec)
                brief = stamp_since(brief, cached["brief"] if cached else None, vec, datetime.now(timezone.utc).isoformat(timespec="seconds"))
                briefs[story["sid"]] = {"version": BRIEF_VERSION, "roster": ROSTER_VERSION, "outlets": outlets_now, "sides": sides_now, "brief": brief,
                                        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                        "openings_read": sum(1 for x in excerpts if x)}
            except Exception as e:
                print(f"  brief failed for {story['sid']}: {e}")
        if not brief:
            return False
        # Once per story: splits with finished checks that a rewrite dropped before keep_checked_splits
        # existed come back from the archived summaries (today and the two days before).
        if brief.get("restored_v") != RESTORE_VERSION:
            for day in ARCHIVE_DAYS_BACK:
                old = archived_brief(day, story["sid"])
                if old:
                    brief = keep_checked_splits(brief, old, claims, vec)
            brief["restored_v"] = RESTORE_VERSION
        # Loaded language: once per summary, a separate small pass over the same coverage, verified in code.
        if brief.get("loaded_v") != LOADED_VERSION and gemini_ok():
            try:
                llines, _ = coverage_lines(arts, side_of, summaries)
                out, usage = gemini_json(LOADED_PROMPT.replace("{coverage}", "\n".join(llines)), LOADED_SCHEMA)
                charge_gemini(usage)
                brief["loaded"] = verify_loaded(out, arts, llines, side_of)
                brief["loaded_v"] = LOADED_VERSION
            except Exception as e:
                print(f"  loaded-language pass failed: {e}")
        # Reader polls: each values question with 2 to 4 neutral answers, plus "Not sure". Once per summary.
        # The id includes a hash of the wording, so a reworded poll is a new poll, never a mix of two.
        if brief.get("values_questions") and brief.get("poll_v") != POLL_VERSION and gemini_ok():
            try:
                out, usage = gemini_json(POLL_PROMPT.replace("{title}", story["working_title"])
                                         .replace("{questions}", "\n".join(f"- {q}" for q in brief["values_questions"])), POLL_SCHEMA, "low")
                charge_gemini(usage)
                polls = []
                for p in out.get("polls", [])[:2]:
                    q = (p.get("question") or "").strip()
                    opts = [o.strip() for o in p.get("options", []) if o.strip() and len(o.strip()) <= 100][:4]
                    if not q or len(q) > 220 or len(opts) < 2 or len({o.casefold() for o in opts}) < len(opts):
                        continue
                    opts.append("Not sure")
                    pid = f"{story['sid']}-{hashlib.sha1(json.dumps([q, opts]).encode()).hexdigest()[:8]}"
                    polls.append({"id": pid, "question": q, "options": opts})
                brief["polls"], brief["poll_v"] = polls, POLL_VERSION
            except Exception as e:
                print(f"  poll pass failed: {e}")
        # Each loaded term is shown in its sentence. Found in code, in text we already read; no model call.
        if any("quotes" not in t for t in brief.get("loaded") or []):
            try:
                qlines, _ = coverage_lines(arts, side_of, summaries)
                loaded_quotes(brief["loaded"], arts, qlines)
            except Exception as e:
                print(f"  loaded-language quotes failed: {e}")
        # Every side's account gets the same chance of a check: if the brief left an account without a
        # claim, ask for the one factual claim it makes (or confirm it makes none). Once per account.
        for d in brief["differences"]:
            for pos in d["positions"]:
                if not pos.get("checkable_claim") and not pos.get("claim_tried") and gemini_ok():
                    try:
                        out, usage = gemini_json(CLAIM_PROMPT.replace("{point}", d["point"]).replace("{says}", pos["says"]), CLAIM_SCHEMA, "low")
                        charge_gemini(usage)
                        pos["checkable_claim"] = (out.get("claim") or "").strip()
                        pos["no_claim"] = not pos["checkable_claim"]
                        pos["claim_tried"] = True
                    except Exception as e:
                        print(f"  claim extraction failed: {e}")
            # an account with no check yet goes first, so the per-scan cap never starves one side
            d["positions"].sort(key=lambda q: bool(q.get("check")))
        # A re-summary rewords claims. Where a side's new claim is undecided and an earlier decided claim from
        # the same side of this story says the same thing, keep the earlier one, so a Confirmed doesn't
        # silently turn into a fresh Unproven. Same side means the claim's outlets share a side and none oppose.
        earlier = [(k, c) for k, c in claims.items() if story["sid"] in c.get("stories", []) and c.get("verdict") in DECIDED]
        used = {p.get("check") for d in brief["differences"] for p in d["positions"]}
        for d in brief["differences"]:
            for pos in d["positions"]:
                cur = claims.get(pos.get("check")) if pos.get("check") else None
                if not pos.get("checkable_claim") or (cur and cur.get("verdict") in DECIDED) or not earlier:
                    continue
                mine = {side_of.get(o) for o in pos["outlets"]} - {"unplaced", None}
                best, best_k = 0.0, None
                for k, c in earlier:
                    theirs = {side_of.get(o) for o in c.get("said_by", [])} - {"unplaced", None}
                    if k in used or not (mine & theirs) or ({"left", "right"} <= (mine | theirs)):
                        continue
                    sim = float(vec([pos["checkable_claim"]])[0] @ vec([c["claim"]])[0])
                    if sim > best:
                        best, best_k = sim, k
                if best_k and best >= CARRY_OVER:
                    print(f"  carry over ({best:.2f}): {claims[best_k]['claim'][:70]}")
                    pos["checkable_claim"], pos["check"] = claims[best_k]["claim"], best_k
                    used.add(best_k)
        # Factual differences are checked against primary sources (cached in the library).
        for d in brief["differences"]:
            if d.get("checkable_claim") and not d.get("check"):  # briefs written before per-side claims
                said_by = sorted({o for p in d["positions"] for o in p["outlets"]})
                d["check"] = check_claim(d["checkable_claim"], story["sid"], said_by)
            for pos in d["positions"]:  # each side's factual claim, checked the same way
                if pos.get("checkable_claim"):
                    pos["checkable_claim"] = deattribute(pos["checkable_claim"], pos["outlets"])
                if pos.get("checkable_claim") and not pos.get("check"):
                    pos["check"] = check_claim(pos["checkable_claim"], story["sid"], pos["outlets"])
        # Ad watch (Texas Election only): claims campaigns make about opponents, in ads or attacks, as the
        # coverage reports them; each is checked like any other claim. Kept in code only where the article it
        # came from names the speaker.
        if story.get("region") == "tx" and brief.get("ad_v") != AD_VERSION and gemini_ok():
            try:
                alines, _ = coverage_lines(arts, side_of, summaries)
                out, usage = gemini_json(AD_PROMPT.replace("{coverage}", "\n".join(alines)), AD_SCHEMA)
                charge_gemini(usage)
                ads, proposed = [], out.get("claims", [])
                for c in proposed[:3]:
                    speaker, assertion = (c.get("speaker") or "").strip(), (c.get("assertion") or "").strip()
                    found = [arts[i - 1]["source"] for i in c.get("articles", []) if isinstance(i, int) and 1 <= i <= len(arts)
                             and speaker and speaker.split()[-1].casefold() in alines[i - 1].casefold()]
                    if speaker and assertion and found:
                        ads.append({"speaker": speaker, "target": (c.get("target") or "").strip(), "kind": c.get("kind", "statement"),
                                    "assertion": assertion, "outlets": sorted(set(found)), "check": None})
                    else:  # say why, so an empty race can be told apart from a filter that is too strict
                        why = "no speaker" if not speaker else "no assertion" if not assertion else \
                            f"speaker not named in cited articles {c.get('articles')}"
                        print(f"  race claim dropped ({why}): {speaker or '?'}: {assertion[:90]}")
                brief["ad_claims"], brief["ad_v"] = ads, AD_VERSION
                print(f"  race claims: {len(proposed)} proposed, {len(ads)} kept, from {len(arts)} articles")
            except Exception as e:
                print(f"  ad watch failed: {e}")
        for a in brief.get("ad_claims", []):
            if not a.get("check"):
                a["check"] = check_claim(a["assertion"], story["sid"], a["outlets"])
        story["brief"] = brief
        story["checks"] = [k for d in brief["differences"] for k in [d.get("check")] + [p.get("check") for p in d["positions"]] if k] \
            + [a["check"] for a in brief.get("ad_claims", []) if a.get("check")]
        # The full story, for stories that will be on Today (facts both sides report), from the brief only.
        if any("left" in f["sides"] and "right" in f["sides"] for f in brief["agreed"]):
            sig = json.dumps(sorted((k, claims[k].get("verdict")) for k in story["checks"] if k in claims))
            material, src = full_material(brief, claims)
            loaded = [t.get("term", "") for t in brief.get("loaded", [])]
            # A stored full story is rewritten when the brief or its checks change, or when a sentence in it fails
            # a rule added since (so a new rule fixes only the stories it catches).
            stale = any(full_sentence_problem(x["text"], x["sources"], src, loaded) for p in (brief.get("full_story") or []) for x in p)
            if (brief.get("full_v") != FULL_VERSION or brief.get("full_sig") != sig or stale) and gemini_ok():
                try:
                    out, usage = gemini_json(FULL_PROMPT.replace("{loaded}", ", ".join(f'"{t}"' for t in loaded) or "(none)")
                                             .replace("{material}", material), FULL_SCHEMA, "low")
                    charge_gemini(usage)
                    paras, dropped = [], 0
                    for para in out.get("paragraphs", [])[:6]:
                        keep = []
                        for sent in para.get("sentences", [])[:4]:
                            text, ids = (sent.get("text") or "").strip(), [i.strip() for i in sent.get("sources", [])]
                            why = full_sentence_problem(text, ids, src, loaded)
                            if why:
                                dropped += 1
                                print(f"  full story sentence dropped ({why}): {text[:90]}")
                            else:
                                keep.append({"text": text, "sources": ids})
                        if keep:
                            paras.append(keep)
                    n = sum(len(p) for p in paras)
                    brief["full_story"] = paras if n >= 3 else None
                    brief["full_v"], brief["full_sig"] = FULL_VERSION, sig
                    print(f"  full story: {n} sentences kept, {dropped} dropped")
                except Exception as e:
                    print(f"  full story failed: {e}")
        # A picture approved for this summary is kept: stable from scan to scan, and no lookup or check repeats
        # (so pictures don't drop when the day's budget is spent). A new summary or rule version re-picks.
        if story["sid"] in FORCE_REPICK and brief.get("repicked") != FORCE_REPICK[story["sid"]]:
            print(f"  repick picture: {FORCE_REPICK[story['sid']]}")
            brief["repicked"] = FORCE_REPICK[story["sid"]]
            brief.pop("image", None), brief.pop("image_alt_v", None)
        if brief.get("image_v") != IMAGES_VERSION or not brief.get("image"):
            found = find_image(story, brief)
            if found:
                brief["image"], brief["image_v"] = found, IMAGES_VERSION
        story["image"] = rotate(brief.get("image"), story["sid"]) if brief.get("image_v") == IMAGES_VERSION else None
        # A second picture of a different subject, for when the home page has already shown the first one
        # higher up (two Trump portraits in two sections). Found once, like the first.
        if story["image"] and brief.get("image_alt_v") != ALT_VERSION:
            brief["image_alt"] = find_image(story, brief, avoid={story["image"]["subject"]})
            brief["image_alt_v"] = ALT_VERSION
        story["image_alt"] = rotate(brief.get("image_alt"), story["sid"]) if story["image"] else None
        shared = [f for f in brief["agreed"] if "left" in f["sides"] and "right" in f["sides"]]
        print(f"  {story['sid']} [{story['topic']}]: {len(shared)} common ground of {len(brief['agreed'])} agreed, {len(brief['differences'])} differences")
        return bool(shared)  # Today shows only what both sides report; no common ground, no slot


    # Every verdict, explained plainly: which part holds, is false, or is missing, and what the sources show,
    # from the checker's finding only. Once per claim. First in the scan: it is cheap, and readers see it on
    # every check, so it should never wait behind summaries and new checks for the day's budget.
    live_sids = {s["sid"] for s in data["stories"]}
    todo = [k for k, c in sorted(claims.items()) if set(c.get("stories", [])) & live_sids and c.get("finding")
            and EXPLAIN_ASK.get(c.get("verdict")) and (c.get("explain_v") != EXPLAIN_VERSION or not explain_ok(c))][:EXPLAIN_PER_SCAN]

    def explain(k):
        c = claims[k]
        ask = EXPLAIN_ASK[c["verdict"]]
        prompt = (EXPLAIN_PROMPT.replace("{claim}", c["claim"]).replace("{verdict}", c["verdict"])
                  .replace("{finding}", c["finding"][:1500]).replace("{part}", ask[0]).replace("{context}", ask[1]))
        out, usage = gemini_json(prompt, EXPLAIN_SCHEMA, "low")
        # One retry, told what was wrong; a line that still breaks a rule is left empty (explain_problem).
        problems = [f"Your {f} line \"{out.get(f)}\" can't be used: {why}." for f in ("part", "context")
                    for why in [line_problem(c, f, (out.get(f) or "").strip())] if why]
        if problems:
            print(f"  explain retry: {' '.join(problems)[:200]}")
            out2, usage2 = gemini_json(prompt + "\n\n" + " ".join(problems) + " Write both lines again.", EXPLAIN_SCHEMA, "low")
            usage = {key: usage.get(key, 0) + usage2.get(key, 0) for key in set(usage) | set(usage2)}
            out = out2
        return k, out, usage

    if todo and gemini_ok():
        with ThreadPoolExecutor(max_workers=6) as pool:
            for fut in [pool.submit(explain, k) for k in todo]:
                try:
                    k, out, usage = fut.result()
                except Exception as e:
                    print(f"  explain failed: {e}")
                    continue
                charge_gemini(usage)
                c = claims[k]
                part, ctx = (out.get("part") or "").strip(), (out.get("context") or "").strip()
                # Held to what readers were promised: the verdict's two plain lines, facts only (explain_problem).
                part, ctx = ("" if line_problem(c, "part", part) else part), ("" if line_problem(c, "context", ctx) else ctx)
                c["explain"] = {"part": part if len(part) <= 240 else "", "context": ctx}
                if c["verdict"] == "Missing context":
                    c["left_out"] = c["explain"]["context"]
                c["explain_v"] = EXPLAIN_VERSION
        print(f"  explained {len(todo)} checks")
    # Each topic: walk its ranking (stories covered by both left- and right-leaning outlets only) until
    # its quota has a real summary, trying at most EXTRA_CANDIDATES more. Only these appear on Today.
    both = lambda s: bool(s["coverage"].get("left")) and bool(s["coverage"].get("right"))
    for topic, quota in TOPIC_QUOTAS.items():
        cands = [s for s in data["stories"] if s.get("related_to") is None and s.get("topic") == topic and both(s)]
        # Daily sections: stories that broke in the last FRESH_HOURS go first, in ranking order; older ones
        # only fill what is left. Weekly sections (span "week") keep their whole pool.
        fresh = [s for s in cands if s.get("span") != "week" and hours_since_broke(s) <= FRESH_HOURS]
        cands = fresh + [s for s in cands if s not in fresh]
        done = 0
        for story in cands[:quota + EXTRA_CANDIDATES]:
            if done >= quota:
                break
            if process(story):
                done += 1
                story["on_today"] = True
        print(f"  {topic}: {done} of {quota} on Today ({len(cands)} stories covered by both sides)")

    # Covered by one side: chosen in code (one_side_lanes), then summarized and checked like any story, a lane at a
    # time so neither side's stories wait behind the other's. Only after Today's sections, inside the same caps.
    osd = lib.setdefault("one_side", {})
    pool = json.loads((ROOT / "data/articles.json").read_text())["articles"] if (ROOT / "data/articles.json").exists() else []
    zero_check = make_zero_check(pool, side_of, data.get("roster") or {}, vec, osd)
    lanes = one_side_lanes(data["stories"], data.get("roster") or {}, osd, datetime.now(timezone.utc), zero_check)
    day_os = osd.setdefault("days", {}).setdefault(today, {"summaries": 0, "left": 0, "right": 0, "gemini_usd": 0.0})
    osd["days"] = {d: v for d, v in osd["days"].items() if d >= cutoff}
    first = "left" if day_os["left"] <= day_os["right"] else "right"
    order = [st for pair in zip(*(lanes[k] + [None] * (ONE_SIDE_LANE - len(lanes[k])) for k in (first, "right" if first == "left" else "left")))
             for st in pair if st]
    new_here = 0
    for st in order:
        k = st["one_side"]["side"]
        can_new = day_os["summaries"] < ONE_SIDE_PER_DAY and new_here < ONE_SIDE_PER_SCAN
        was = (briefs.get(st["sid"]) or {}).get("at")
        if was is None and not can_new:
            continue
        g0 = spend["gemini_usd"]
        process(st, rebrief=can_new)
        if (briefs.get(st["sid"]) or {}).get("at") != was:
            day_os["summaries"] += 1
            day_os[k] += 1
            new_here += 1
        day_os["gemini_usd"] = round(day_os["gemini_usd"] + spend["gemini_usd"] - g0, 4)
    data["one_side"] = {"min": ONE_SIDE_MIN, "hours": ONE_SIDE_HOURS,
                        "lanes": {k: [st["sid"] for st in v] for k, v in lanes.items()},
                        "picked_up": sorted(osd.get("picked_up", []), key=lambda r: r["seen_at"], reverse=True),
                        "first": "left" if datetime.now(ZoneInfo("America/New_York")).date().toordinal() % 2 else "right"}
    print(f"  one side: left {len(lanes['left'])}, right {len(lanes['right'])}; {day_os['summaries']} summaries today "
          f"(left {day_os['left']}, right {day_os['right']}), ${day_os['gemini_usd']:.2f}")

    frame_faces(data["stories"], lib)
    track_changes(lib, data["stories"])
    shown = [s for s in data["stories"] if s.get("on_today") or (s.get("one_side") and s.get("brief"))]
    write_archive(shown, data.get("feeds", []))
    write_share_pages(shown)

    # People pictured on 4+ stories on Today in 7 days, with no photo rotation yet: flagged for hand-picked photos
    # (the rules are in images.py). Read from data/library.json, "photo_repeats".
    reps = lib.setdefault("photo_repeats", {})
    seen = reps.setdefault("seen", {})
    for st in data["stories"]:
        im = st.get("image") or {}
        if st.get("on_today") and im.get("wikidata") and f"{im['subject']}. Photo:" in im.get("caption", ""):
            seen.setdefault(im["wikidata"], {"subject": im["subject"], "stories": {}})["stories"].setdefault(st["sid"], today)
    week = (datetime.now(timezone.utc) - timedelta(days=7)).date().isoformat()
    for q in list(seen):
        seen[q]["stories"] = {sid: d for sid, d in seen[q]["stories"].items() if d >= week}
        if not seen[q]["stories"]:
            del seen[q]
    reps["wanted"] = sorted(({"subject": v["subject"], "wikidata": q, "stories_7d": len(v["stories"])} for q, v in seen.items()
                             if len(v["stories"]) >= 4 and q not in ROTATION), key=lambda w: -w["stories_7d"])
    for w in reps["wanted"]:
        print(f"  photo rotation wanted: {w['subject']} on {w['stories_7d']} stories in 7 days")

    live = {s["sid"] for s in data["stories"]}
    lib["briefs"] = {k: v for k, v in briefs.items() if k in live}
    lib["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lib["ai_errors"] = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "count": len(AI_ERRORS), "last": AI_ERRORS[-3:]}
    lib["caps"] = {"anthropic_daily_usd": ANTHROPIC_DAILY_USD, "gemini_daily_usd": GEMINI_DAILY_USD,
                   "today_gemini_cap": gemini_cap, "today_anthropic_cap": anthropic_cap, "testing_until": TESTING_UNTIL,
                   "gemini_free_searches": GEMINI_FREE_SEARCHES, "search_usd": SEARCH_USD, "new_claims_per_day": new_per_day}
    (ROOT / "data/library.json").write_text(json.dumps(lib, indent=1))
    stories_path.write_text(json.dumps(data, indent=1))
    write_capsule(data, lib)
    (ROOT / "data/.summarized").write_text(datetime.now(timezone.utc).isoformat())  # deploy publishes stories.json only with this
    print(f"check_today: {state['new_this_scan']} new claims · today anthropic ${spend["anthropic_usd"]:.2f}/{anthropic_cap:.2f} · "
          f"gemini ${spend['gemini_usd']:.2f}/{gemini_cap:.2f}, searches {spend['gemini_searches']} ({GEMINI_FREE_SEARCHES} free), "
          f"thinking tokens {THOUGHTS['tokens']} over {THOUGHTS['calls']} calls")
    return 0


def passage(url, quote, width=400):
    """The text around a verified quote on its own page, read by our code (never published)."""
    text, _ = C.fetch_page(url)
    if not text:
        text, _ = C.fetch_via_anthropic(url)
    if not text:
        return None
    q = C.norm(quote)
    i = text.find(q[:80])
    if i < 0:
        return None
    return text[max(0, i - width): i + len(q) + width]


_STOP = {"the", "a", "an", "and", "of", "in", "on", "at", "to", "for", "is", "was", "were", "by", "with", "that", "this", "as", "from"}


def mentions(url, claim, already, limit=4):
    """Sentences on the evidence page that name the claim's proper nouns or numbers and are not already
    shown, so a quote can be tied to the place, case or person the claim names. Our own read of the page."""
    text, _ = C.fetch_page(url)
    if not text:
        text, _ = C.fetch_via_anthropic(url)
    if not text:
        return []
    names = re.findall(r"(?:[A-Z][\w'.-]+(?:\s+(?:[A-Z][\w'.-]+|of|the))*)", claim)
    terms = {C.norm(t).strip(".,;:'\"") for t in names}
    terms = {t for t in terms if t not in _STOP and len(t) > 3} | set(C.numbers_in(claim))
    seen, out = C.norm(already), []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if len(sent) > 400 or sent in seen:
            continue
        if any(t in sent for t in terms):
            out.append(sent.strip())
            if len(out) >= limit:
                break
    return out


_QUOTED = re.compile(r"[\u201c\"][^\u201d\"]{1,300}[\u201d\"]|\u2018[^\u2019]{1,300}\u2019")


def verify_loaded(raw, arts, lines, side_of):
    """Keep a term only where it appears, outside quotation marks, in the cited outlet's own line (headline,
    summary or opening). Outlets and sides come from those verified lines, never from the model."""
    n, out, seen = len(arts), [], set()
    for t in raw.get("terms", [])[:10]:
        term = (t.get("term") or "").strip().strip('"\u201c\u201d')
        key = re.sub(r"(es|s)$", "", term.casefold())  # "Leftist" and "Leftists" are one term
        if not term or len(term) > 60 or key in seen:
            continue
        found = []
        for i in t.get("articles", []):
            if isinstance(i, int) and 1 <= i <= n:
                own = _QUOTED.sub(" ", lines[i - 1].split(": ", 1)[-1])
                if term.casefold() in own.casefold():
                    found.append(arts[i - 1]["source"])
        if found:
            seen.add(key)
            outlets = sorted(set(found))
            out.append({"term": term, "outlets": outlets, "sides": sorted({side_of.get(o, "unplaced") for o in outlets}),
                        "why": (t.get("why") or "").strip(), "neutral": (t.get("neutral") or "").strip()})
    return out


_SENTENCE = re.compile(r"(?<=[.!?\u201d\"])\s+(?=[A-Z\u201c\"])")


def loaded_quotes(terms, arts, lines, limit=220):
    """For each loaded term, the sentence it appears in, from up to two of the outlets that used it: the
    headline, summary or opening line we read, outside quotation marks, trimmed around the term. A
    sentence is a short quotation for comment, with a link; whole openings are never stored."""
    for t in terms:
        if "quotes" in t:
            continue
        term, quotes = t["term"].casefold(), []
        for i, a in enumerate(arts):
            if len(quotes) == 2 or a["source"] not in t["outlets"] or any(q["outlet"] == a["source"] for q in quotes):
                continue
            body = lines[i].split(": ", 1)[-1] if i < len(lines) else ""
            for part in body.split(" | "):
                part = part[len("Opening: "):] if part.startswith("Opening: ") else part
                sent = next((x for x in _SENTENCE.split(part) if term in _QUOTED.sub(" ", x).casefold()), None)
                if sent:
                    sent = sent.strip()
                    if len(sent) > limit:  # keep a window around the term
                        at = sent.casefold().find(term)
                        lo = max(0, at - limit // 2)
                        sent = ("\u2026" if lo else "") + sent[lo:lo + limit].strip() + "\u2026"
                    quotes.append({"outlet": a["source"], "text": sent, "url": a["url"]})
                    break
        t["quotes"] = quotes


def coverage_lines(arts, side_of, summaries):
    """The numbered coverage lines the models read: outlet, lean, headline, summary, and the article's opening."""
    with ThreadPoolExecutor(max_workers=8) as pool:
        excerpts = list(pool.map(excerpt, [a["url"] for a in arts]))
    lines = []
    for i, (a, ex) in enumerate(zip(arts, excerpts)):
        summ = (summaries.get(a["url"]) or "")[:300]
        lines.append(f"{i + 1}. {a['source']} ({side_of.get(a['source'], 'unplaced')}): {a['title']}"
                     + (f" | {summ}" if summ else "") + (f" | Opening: {ex}" if ex else ""))
    return lines, excerpts


_TITLES = re.compile(r"^(?:(?:Former|Vice|Deputy|Acting|Ex-|U\.S\.|US|White House|Press|Prime|President|Secretary|Minister|Senator|Sen\.|Rep\.|"
                     r"Representative|Gov\.|Governor|Lt\.|Judge|Justice|Mayor|Attorney|General|Speaker|Leader|Chief|Democratic|Republican|"
                     r"Candidate|Ambassador|Director|Commissioner|Chairman|Chair|Pope|King|Queen)\s+)+")


def person_names(text):
    """Candidate full names in a headline or sentence: runs of two or three capitalized words, with leading
    titles removed ("President Donald Trump" -> "Donald Trump"). Lookups decide which are really people."""
    out = []
    for run in re.findall(r"(?:[A-Z][a-zA-Z'\u2019.-]+\s+){1,5}[A-Z][a-zA-Z'\u2019-]+", text):
        run = _TITLES.sub("", run.strip())
        words = run.split()
        if 2 <= len(words) <= 3 and run not in out:
            out.append(run)
        elif len(words) > 3 and " ".join(words[-2:]) not in out:
            out.append(" ".join(words[-2:]))
    return out


def pick_articles(arts, side_of, n):
    """Up to n articles, one per outlet first (newest), dealt round-robin left, right, center, unplaced,
    so the brief hears both sides equally whatever the article counts."""
    ordered = sorted(arts, key=lambda a: a.get("published") or "", reverse=True)
    seen, firsts, rest = set(), [], []
    for a in ordered:
        (rest if a["source"] in seen else firsts).append(a)
        seen.add(a["source"])
    by_side = {k: [] for k in ("left", "right", "center", "unplaced")}
    for a in firsts + rest:
        by_side[side_of.get(a["source"], "unplaced")].append(a)
    out = []
    while len(out) < n and any(by_side.values()):
        for k in by_side:
            if by_side[k] and len(out) < n:
                out.append(by_side[k].pop(0))
    return out


_P = re.compile(r"<p\b[^>]*>(.*?)</p>", re.S | re.I)
_JUNK = re.compile(r"subscribe|sign up|newsletter|cookie|all rights reserved|advertisement|click here", re.I)


def excerpt(url):
    """The opening paragraphs of an article, read for the brief only (never stored or published).
    A page that refuses us, or has no readable paragraphs, gives an empty string."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": C.UA})
        with urllib.request.urlopen(req, timeout=12, context=C.SSL_CTX) as r:
            page = r.read(2_000_000).decode("utf-8", "replace")
    except Exception:
        return ""
    page = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", page, flags=re.S | re.I)
    out = ""
    for m in _P.finditer(page):
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()
        t = __import__("html").unescape(t)
        if len(t) >= 80 and not _JUNK.search(t):
            out += t + " "
            if len(out) >= EXCERPT_CHARS:
                break
    return out[:EXCERPT_CHARS].strip()


def _live_json(url):
    """A JSON file from the live site; None if it doesn't exist yet. Other failures raise."""
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": C.UA}), timeout=20, context=C.SSL_CTX) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def write_share_pages(stories):
    """One small page per story on Today, at s/<sid>.html, for link previews: messaging apps and social sites
    read its title, description and picture without running the site's script. People go straight on to
    the story. The link carries the day, so it still opens once the story has left Today."""
    from html import escape
    day = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    out = ROOT / "data/share"
    out.mkdir(parents=True, exist_ok=True)
    for st in stories:
        brief = st.get("brief") or {}
        shared = [f["fact"] for f in brief.get("agreed", []) if "left" in f.get("sides", []) and "right" in f.get("sides", [])]
        splits = len(brief.get("differences", []))
        desc = f"Left and right agree: {shared[0]}" if shared else "What left- and right-leaning outlets agree on, and where they split."
        if st.get("one_side"):
            o = st["one_side"]
            k, x = o["side"], "right" if o["side"] == "left" else "left"
            desc = (f"{len(o['covered'])} of {len(o['roster'][k])} {k}-leaning outlets covered this. "
                    f"0 of {len(o['roster'][x])} {x}-leaning outlets did.")
            splits = 0
        if len(desc) > 200:
            desc = desc[:197].rsplit(" ", 1)[0] + "\u2026"
        if splits:
            desc += f" Plus {splits} point{'s' if splits != 1 else ''} where they split."
        story_url = f"{SITE_URL}story.html?s={st['sid']}&d={day}"
        image = f"{SITE_URL}{st['image']['src']}" if st.get("image") and st["image"].get("src") else f"{SITE_URL}og-card-v1.png"
        e = lambda t: escape(t, quote=True)
        (out / f"{st['sid']}.html").write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{e(st['working_title'])} \u00b7 fACTUAL</title>
<meta name="description" content="{e(desc)}">
<meta name="robots" content="noindex">
<link rel="canonical" href="{e(story_url)}">
<meta property="og:type" content="article"><meta property="og:site_name" content="fACTUAL">
<meta property="og:title" content="{e(st['working_title'])}"><meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{SITE_URL}s/{st['sid']}.html"><meta property="og:image" content="{e(image)}">
<meta name="twitter:card" content="summary_large_image">
<meta http-equiv="refresh" content="0; url={e(story_url)}">
<script>location.replace({json.dumps(story_url)})</script>
</head><body><p><a href="{e(story_url)}">{e(st['working_title'])}</a></p></body></html>
""")
    print(f"  share pages: {len(stories)}")


def write_capsule(data, lib):
    """The Texas demo's time capsule: until the edition's cutoff, every scan saves the whole of Today (all
    sections, Texas Election included) with the checks it shows, at data/capsule/<key>/tx.json. After the
    cutoff nothing is written, so the last copy on the server is the capsule. The key is a repo secret
    (CAPSULE_KEY), never in the code: only a link that carries it can open the capsule."""
    key = os.environ.get("CAPSULE_KEY", "").strip()
    tx = (data.get("regions") or {}).get("tx")
    if not tx or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", key):
        return
    if datetime.now(timezone.utc) >= datetime.fromisoformat(tx["until"]):
        print("  capsule: frozen (past the Texas cutoff); not written")
        return
    on = [s for s in data["stories"] if s.get("on_today")]
    checks = {k for s in on for k in s.get("checks", [])}
    capsule = {"edition": "tx", "frozen_at": tx["until"], "scanned_at": data["scanned_at"], "regions": data.get("regions"),
               "feeds": data.get("feeds", []), "stories": on,
               "library": {"claims": {k: c for k, c in lib.get("claims", {}).items() if k in checks}}}
    folder = ROOT / "data/capsule"
    (folder / key).mkdir(parents=True, exist_ok=True)
    (folder / key / "tx.json").write_text(json.dumps(capsule))
    (folder / ".htaccess").write_text("Options -Indexes\n")  # never list the folder, so the key can't be found
    (folder / "index.html").write_text("")
    print(f"  capsule: {len(on)} stories, {len(capsule['library']['claims'])} checks")


_ARCHIVED = {}


def archived_brief(day, sid):
    """A story's summary as the archive kept it on a given day, or None. Each day's file is read once per scan."""
    if day not in _ARCHIVED:
        try:
            _ARCHIVED[day] = _live_json(f"{ARCHIVE_URL}{day}.json") or {}
        except Exception:
            _ARCHIVED[day] = {}
    return ((_ARCHIVED[day].get("stories") or {}).get(sid) or {}).get("brief")


def track_changes(lib, stories):
    """Every verdict that changes after it was published (Heston, 2026-10-30: a public corrections log). Compared
    with the verdict last published, each scan; a change goes into lib["corrections"] with when and why. Code only."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    day = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    on_today = {st["sid"]: st for st in stories if st.get("on_today")}
    seen = lib.setdefault("published_verdicts", {})
    log = lib.setdefault("corrections", [])
    for k, c in lib.get("claims", {}).items():
        v, was = c.get("verdict"), seen.get(k)
        if was and was["verdict"] != v:
            st = next((on_today[s] for s in c.get("stories", []) if s in on_today), None)  # linked by title and day
            log.append({"key": k, "claim": c["claim"], "from": was["verdict"], "to": v, "at": now,
                        "why": c.get("change_why") or "Checked again.",
                        "story": {"sid": st["sid"], "title": st.get("working_title", ""), "day": day} if st else None})
            print(f"  correction: {was['verdict']} -> {v}: {c['claim'][:70]}")
        if not was or was["verdict"] != v:
            seen[k] = {"verdict": v, "at": now}
        c.pop("change_why", None)
    if "corrections_since" not in lib:
        lib["corrections_since"] = now  # changes before this scan were not recorded


def frame_faces(stories, lib):
    """Give every picture the place of its face (images.face), so the site frames the face, not a fixed band.
    Found once per file and kept in the library by src; "no clear face" is kept too. A file that can't be read
    or a missing OpenCV skips this scan and is tried again: a picture without it keeps the default framing."""
    faces = lib.setdefault("faces", {})
    for st in stories:
        for k in ("image", "image_alt"):
            im = st.get(k)
            if not im or not im.get("src"):
                continue
            src = im["src"]
            if src not in faces:
                try:
                    local = ROOT / ("web" if src.startswith("img/") else "") / src
                    if local.exists():
                        raw = local.read_bytes()
                    else:
                        req = urllib.request.Request(SITE_URL + src, headers={"User-Agent": "fACTUAL-scan/0.1 (+https://hestonmiles.com/factual/)"})
                        with urllib.request.urlopen(req, timeout=20, context=C.SSL_CTX) as r:
                            raw = r.read(8_000_000)
                    faces[src] = face(raw)
                except Exception as e:
                    print(f"  face not read for {src}: {e}")
                    continue
            if faces[src]:
                im["face"] = faces[src]
            else:
                im.pop("face", None)


def _when(a):
    """An article's time from its feed, and whether the feed gives only the day (Just the News: always midnight)."""
    p = a.get("published") or ""
    try:
        t = datetime.fromisoformat(p)
    except ValueError:
        return None, False
    return t, p.endswith("T00:00:00+00:00")


def first_report(arts, outlets):
    """The earliest article from these outlets: (time, outlet, day_only). A day-only article counts as first only
    when that whole day ends before every timed one."""
    timed = sorted((t, a["source"]) for a in arts if a["source"] in outlets for t, d in [_when(a)] if t and not d)
    dated = sorted((t, a["source"]) for a in arts if a["source"] in outlets for t, d in [_when(a)] if t and d)
    if dated and (not timed or dated[0][0] + timedelta(days=1) <= timed[0][0]):
        return dated[0][0], dated[0][1], True
    return (timed[0][0], timed[0][1], False) if timed else (None, None, False)


def make_zero_check(pool, side_of, roster, vec, osd):
    """zero_check(story, side): True if an article from that side in the 7-day pool reports the same event
    (ZERO_SIM against the story's centre). Each scan's held-out stories and near misses go to osd for review."""
    as_text = lambda a: f"{a['title']}. {(a.get('summary') or '')[:300]}"  # as cluster.py embeds them
    side_vecs = {}
    osd["held_out"], osd["near"] = [], []

    def zero_check(st, o):
        if o not in side_vecs:
            arts = [a for a in pool if side_of.get(a["source"]) == o and a["source"] in roster.get(o, [])]
            side_vecs[o] = (arts, vec([as_text(a) for a in arts]) if arts else None)
        arts, P = side_vecs[o]
        if P is None:
            return False
        cen = vec([as_text(a) for a in st["articles"]]).mean(axis=0)
        sims = P @ (cen / np.linalg.norm(cen))
        i = int(np.argmax(sims))
        rec = {"sid": st["sid"], "title": st["working_title"], "side": o, "by": arts[i]["source"],
               "match": arts[i]["title"], "sim": round(float(sims[i]), 3)}
        if sims[i] >= ZERO_SIM:
            osd["held_out"].append(rec)
            print(f"  one side: held out ({o} reported it, {sims[i]:.2f}, {arts[i]['source']}): {st['working_title'][:60]}")
            return True
        if sims[i] >= ZERO_NEAR:
            osd["near"].append(rec)
        return False
    return zero_check


def one_side_lanes(stories, roster, state, now, zero_check=None):
    """Covered by one side, in code only. A lane story: ONE_SIDE_MIN+ outlets on one side, none on the other, its
    newest article within ONE_SIDE_HOURS; ranked by the share of its side's own roster that covered it. A story
    that was listed and that the other side then covered goes to state["picked_up"], with who was first and when,
    by the articles' own times. Marks each lane story with story["one_side"]."""
    other = {"left": "right", "right": "left"}
    lanes = {"left": [], "right": []}
    newest = lambda s: max((t for a in s["articles"] for t, _ in [_when(a)] if t), default=None)
    # Grouping can split one event in two (10-30: The Epoch Times' peptide article sat in a linked story, so the
    # main one read "0 right-leaning"). A story's linked stories count toward its coverage.
    by_id = {s.get("id"): s for s in stories}
    linked = {}
    for s in stories:
        for r in s.get("related") or []:
            linked.setdefault(s.get("id"), set()).add(r)
            linked.setdefault(r, set()).add(s.get("id"))
        if s.get("related_to") is not None:
            linked.setdefault(s.get("id"), set()).add(s["related_to"])
            linked.setdefault(s["related_to"], set()).add(s.get("id"))
    def sides_with_links(st):
        cov = {k: set(st["coverage"].get(k, [])) for k in ("left", "center", "right")}
        for i in linked.get(st.get("id"), ()):
            for k in cov:
                cov[k] |= set((by_id.get(i) or {}).get("coverage", {}).get(k, []))
        return cov
    for st in stories:
        if st.get("related_to") is not None or st.get("region") or st.get("on_today"):
            continue
        n = newest(st)
        if not n or (now - n).total_seconds() > ONE_SIDE_HOURS * 3600:
            continue
        cov, wide = st["coverage"], sides_with_links(st)
        for k in lanes:
            if len(cov.get(k, [])) >= ONE_SIDE_MIN and not wide[other[k]] and roster.get(k) \
                    and not (zero_check and zero_check(st, other[k])):
                lanes[k].append(st)
    for k in lanes:
        lanes[k] = sorted(lanes[k], key=lambda s: (len(s["coverage"][k]) / len(roster[k]), newest(s)), reverse=True)[:ONE_SIDE_LANE]
        for st in lanes[k]:
            t, src, day_only = first_report(st["articles"], set(st["coverage"][k]))
            st["one_side"] = {"side": k, "covered": sorted(st["coverage"][k]), "center": sorted(st["coverage"].get("center", [])),
                              "roster": {x: roster.get(x, []) for x in ("left", "center", "right")},
                              "first_at": t.isoformat() if t else None, "first_by": src, "first_day_only": day_only}

    by_sid = {s["sid"]: s for s in stories}
    tracked = state.setdefault("tracked", {})
    picked = state.setdefault("picked_up", [])
    stamp = now.isoformat(timespec="seconds")
    for sid, tr in list(tracked.items()):
        st = by_sid.get(sid)
        if st is None:  # aged out of the scan's window, still one-sided: nothing to report
            del tracked[sid]
            continue
        o = other[tr["side"]]
        if not st["coverage"].get(o):
            continue
        t, src, day_only = first_report(st["articles"], set(st["coverage"][o]))
        b, bsrc, b_day = first_report(st["articles"], set(st["coverage"].get(tr["side"], [])))
        if t and b and t >= b:  # the other side's first report came after the first one, by their own times
            picked.append({"sid": sid, "title": st["working_title"], "side": tr["side"], "by": src, "at": t.isoformat(),
                           "day_only": day_only, "broke_at": b.isoformat(), "broke_by": bsrc, "broke_day_only": b_day,
                           "listed_at": tr["listed_at"], "seen_at": stamp})
            print(f"  picked up: {src} ({o}) on {st['working_title'][:60]}")
        del tracked[sid]
    for k in lanes:
        for st in lanes[k]:
            tracked.setdefault(st["sid"], {"side": k, "listed_at": stamp})
    keep = (now - timedelta(days=PICKED_UP_DAYS)).isoformat()
    state["picked_up"] = [r for r in picked if r["seen_at"] >= keep]
    return lanes


def write_archive(stories, feeds):
    """Keep every story that was on Today, by day (U.S. Eastern), so the site builds an archive. A story
    keeps its latest summary for the day. If the live archive can't be read, skip: never overwrite it."""
    day = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    try:
        arch = _live_json(f"{ARCHIVE_URL}{day}.json") or {"date": day, "stories": {}}
        index = _live_json(f"{ARCHIVE_URL}index.json") or {"days": []}
    except Exception as e:
        print(f"  archive not readable ({e}); not writing it this scan")
        return
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    keep = ("sid", "working_title", "topic", "span", "outlets", "sources", "coverage", "articles", "checks", "image", "image_alt", "one_side")
    for st in stories:
        rec = {k: st[k] for k in keep if k in st}
        rec["brief"] = {k: v for k, v in st["brief"].items() if k != "dropped_agreed"}
        rec["archived_at"] = now
        arch["stories"][st["sid"]] = rec
    arch["feeds"] = feeds
    arch["updated_at"] = now
    out = ROOT / "data/archive"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{day}.json").write_text(json.dumps(arch, indent=1))
    counts = {}
    for rec in arch["stories"].values():
        counts[rec.get("topic", "other")] = counts.get(rec.get("topic", "other"), 0) + 1
    days = [d for d in index["days"] if d["date"] != day] + [{"date": day, "count": len(arch["stories"]), "topics": counts}]
    index["days"] = sorted(days, key=lambda d: d["date"], reverse=True)
    (out / "index.json").write_text(json.dumps(index, indent=1))
    print(f"  archive {day}: {len(arch['stories'])} stories")


def deattribute(claim, outlets):
    """'Breitbart reported that X' checks only what an outlet said. Check X itself."""
    names = "|".join(re.escape(o) for o in sorted(outlets, key=len, reverse=True))
    out = re.sub(rf"^(?:the\s+)?(?:{names})\s+(?:reported|reports|says|said|states|stated|writes|wrote)\s+(?:that\s+)?",
                 "", claim.strip(), flags=re.I) if names else claim.strip()
    return out[:1].upper() + out[1:]


def hours_since_broke(story):
    """Hours since a story's first article was published; very large when no article has a date."""
    times = []
    for a in story.get("articles", []):
        try:
            t = datetime.fromisoformat((a.get("published") or "").replace("Z", "+00:00"))
            times.append(t if t.tzinfo else t.replace(tzinfo=timezone.utc))
        except ValueError:
            pass
    return (datetime.now(timezone.utc) - min(times)).total_seconds() / 3600 if times else 1e9


def keep_checked_splits(new, old, claims, vec, limit=3):
    """A rewrite may refresh the story and add splits, but a split whose claim already has a finished check
    stays exactly as it was. Rewrites had been choosing different claims, so a Confirmed fell off the page
    and a fresh claim sat at "Checking" until the next day's budget. A new, unchecked split on the same
    point as a kept one is that split reworded, and is dropped."""
    if not old:
        return new
    done = lambda p: bool(p.get("check")) and (claims.get(p["check"]) or {}).get("verdict") in DECIDED
    checked = lambda d: any(done(p) for p in d["positions"])
    current = new.get("differences", [])
    have = {p.get("check") for d in current for p in d["positions"] if p.get("check")}
    kept = [d for d in old.get("differences", []) if checked(d) and not ({p.get("check") for p in d["positions"]} & have)]
    if not kept:
        return new
    mine = [d for d in current if checked(d)]
    fresh = [d for d in current if not checked(d)]
    if fresh:
        same = vec([d["point"] for d in fresh]) @ vec([d["point"] for d in kept]).T
        fresh = [d for d, row in zip(fresh, same) if float(row.max()) < 0.85]
    new["differences"] = (kept + mine + fresh)[:max(limit, len(kept) + len(mine))]
    return new


NEW_SAME = 0.85   # a rewritten fact this close to an earlier one is that fact reworded, not new
# Measured 10-30 on 107 facts against the day before's: rewordings scored 0.87 to 0.97; facts with a new detail
# mostly under 0.80. Two rewordings at 0.82 still count as new (the safe side: nothing new is hidden).


def stamp_since(new, old, vec, now):
    """When each agreed fact and split first appeared ("since"), for "New since you last read" on the reader's
    device. A fact carries its old stamp across a rewrite when the wording is the same or NEW_SAME close; a fact
    from before stamping began has none and is never shown as new."""
    for field, text in (("agreed", lambda x: x["fact"]), ("differences", lambda x: x["point"])):
        items, before = new.get(field, []), (old or {}).get(field, [])
        if not items:
            continue
        if not before:
            for x in items:
                x["since"] = now
            continue
        sims = vec([text(x) for x in items]) @ vec([text(x) for x in before]).T
        for x, row in zip(items, sims):
            j = int(row.argmax())
            x["since"] = before[j].get("since") if float(row[j]) >= NEW_SAME else now
    return new


def build_brief(raw, arts, lines, side_of, ask, charge):
    """Keep only what the coverage supports: valid article numbers, and agreed facts that at least two
    different outlets state in their own headline or summary."""
    n = len(arts)
    valid = lambda idx: sorted({i for i in idx if isinstance(i, int) and 1 <= i <= n})
    outlets = lambda idx: sorted({arts[i - 1]["source"] for i in idx})

    # Common ground first, then other agreed facts; both pass the same confirmation, and the sides each
    # fact is confirmed on (not the writer's say-so) decide whether the page calls it common ground.
    seen, cands = set(), []
    for a in raw.get("common_ground", [])[:6] + raw.get("agreed", [])[:3]:
        key = a.get("fact", "").strip().casefold()
        if key and key not in seen:
            seen.add(key); cands.append(a)
    agreed = [(a["fact"].strip(), valid(a["articles"])) for a in cands]
    agreed = [(f, idx) for f, idx in agreed if len(outlets(idx)) >= MIN_OUTLETS_AGREED]
    confirmed, dropped = [], []
    for a in cands:
        f, idx = a.get("fact", "").strip(), valid(a.get("articles", []))
        if f and len(outlets(idx)) < MIN_OUTLETS_AGREED:
            dropped.append({"fact": f, "why": f"cited by {len(outlets(idx))} outlet(s)"})
    if agreed:
        facts = "\n".join(f"{j + 1}. {f}" for j, (f, _) in enumerate(agreed))
        # Confirm against every article, not only the ones the brief cited: an outlet that states the
        # fact counts whether or not the brief writer listed it. Missing one would hide common ground.
        # Pure matching, so low thinking: same answer, fewer billed thinking tokens.
        out, usage = ask(CONFIRM_PROMPT.replace("{facts}", facts).replace("{articles}", "\n".join(lines)), CONFIRM_SCHEMA, "low")
        charge(usage)
        stated = {f["fact"]: valid(f["stated_by"]) for f in out.get("facts", [])}
        for j, (fact, idx) in enumerate(agreed):
            by = stated.get(j + 1, [])  # an outlet counts if its own headline or summary states it
            if len(outlets(by)) >= MIN_OUTLETS_AGREED:
                confirmed.append({"fact": fact, "reported_by": outlets(by),
                                  "sides": sorted({side_of.get(o, "unplaced") for o in outlets(by)})})
            else:
                dropped.append({"fact": fact, "why": f"confirmed in {len(outlets(by))} outlet(s): {', '.join(outlets(by))}"})

    differences = []
    for d in raw.get("differences", [])[:3]:
        positions = [{"says": p["says"].strip(), "outlets": outlets(valid(p["articles"])),
                      "crux": c if (c := (p.get("crux") or "").strip()) and c in p["says"] and len(c) < len(p["says"].strip()) else "",
                      "checkable_claim": (p.get("checkable_claim") or "").strip(), "check": None} for p in d.get("positions", [])[:3]]
        positions = [p for p in positions if p["says"] and p["outlets"]]
        if d.get("point", "").strip() and positions:
            differences.append({"point": d["point"].strip(), "positions": positions,
                                "checkable_claim": (d.get("checkable_claim") or "").strip(), "check": None})
    values = [q.strip() for q in raw.get("values_questions", [])[:2] if q.strip()]
    subj = raw.get("main_subject") or {}
    return {"agreed": confirmed, "dropped_agreed": dropped, "differences": differences, "values_questions": values,
            "main_subject": {"name": (subj.get("name") or "").strip(), "kind": subj.get("kind", "none")}}


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never block the scan; the site keeps last hour's results
        print(f"check_today failed: {type(e).__name__}: {e}")
        sys.exit(0)
