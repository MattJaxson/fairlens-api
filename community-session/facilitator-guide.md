# District 3 Community AI Fairness Rating Session
## Facilitator Guide

**Purpose:** District 3 residents set their own fairness standard for AI systems
operating in their community — starting with Emily, the AI voice agent handling
resident service calls.

**Duration:** 90 minutes
**Participants:** 10-15 District 3 residents
**Location:** TBD (District 3 council office or community center)
**Facilitator:** Matt Jackson
**Sponsor:** Councilman Scott Benson, District 3

---

## Before the Session

### Room Setup
- Chairs in a circle or U-shape (not classroom rows — this is a conversation)
- One flip chart or whiteboard visible to everyone
- Printed participant forms (one per person)
- Printed one-page scenario cards (4 scenarios)
- Pens
- One laptop to record the provenance data at the end
- Do NOT project a screen during the session — keep it human

### What to Bring
- [ ] 20 printed Participant Intake Forms
- [ ] 20 printed Scenario Cards (all 4 scenarios on one sheet)
- [ ] 5 printed copies of the Community Fairness Standard (for signing at end)
- [ ] Sign-in sheet (name, neighborhood, contact info for follow-up)
- [ ] Pens
- [ ] Laptop (closed until Part 3)
- [ ] Business cards or one-pager about FairLens (leave-behind, not a pitch)

---

## Session Flow

### Opening (10 minutes)

**Councilman Benson introduces** (3 minutes):
- Why he invited everyone
- What Emily is and why the city is using it
- Why he wants District 3 to have a voice in how it's evaluated

**You introduce yourself** (3 minutes):
- Who you are (Detroit, Morehouse, building fairness tools)
- What today is: "You're going to set the standard that this AI system
  has to meet. Not the federal government. Not the company that built it. You."
- What today is NOT: a tech demo, a sales pitch, a survey that disappears

**Ground rules** (2 minutes):
- Every opinion matters equally
- No wrong answers — we're asking what YOU think is fair, not what the law says
- Everything said here is documented and attributed to "District 3 residents"
  (not individual names) unless someone wants to be named
- We will come back in 6 months to check whether the standard is being met

---

### Part 1: Experience Sharing (20 minutes)

**Goal:** Get people talking about real experiences before introducing any numbers.

Ask the room (open discussion, not round-robin):

1. "Has anyone here called a city service line in the last year? What was that like?"

2. "Has anyone interacted with an automated phone system — city, bank, doctor's
   office — where it didn't understand you or hung up on you?"

3. "For those who've used Emily or heard about it — what concerns you? What
   sounds useful?"

**What you're listening for:**
- Specific failure modes (didn't understand accent, hung up, wrong priority)
- Trust concerns (who hears my data, is this replacing a real person)
- What "working well" means to them in their own words

**Write on the flip chart** the key themes as they come up. These become the
"favorable outcome" definition in Part 2.

---

### Part 2: Setting the Standard (40 minutes)

#### Step A: Define What "Fair" Looks Like (15 minutes)

Based on Part 1, synthesize with the room:

> "Based on what you've said, it sounds like a successful call to Emily means
> [summarize their words]. Does that capture it? What would you add or change?"

Get explicit agreement. Write the final definition on the flip chart. This
becomes the **favorable outcome definition** in the CDF v1.0 record.

Examples of what they might say:
- "The call gets routed to the right department"
- "The system understands what I'm saying the first time"
- "Emergencies get flagged immediately, not treated like routine"
- "I don't have to repeat myself three times"

#### Step B: The Scenarios (15 minutes)

Hand out the scenario cards. Read each one aloud:

**Scenario 1: Equal Performance**
> Emily correctly handles calls from White residents 80% of the time and
> Black residents 80% of the time.

Ask: "Is this fair?" (Most will say yes. This establishes baseline.)

**Scenario 2: The Gap**
> Emily correctly handles calls from White residents 80% of the time and
> Black residents 55% of the time.

Ask: "Is this fair?" Then: "Is this acceptable even temporarily while
they fix it?"

**Scenario 3: The Legal Minimum**
> The federal government says as long as Black residents get at least 64%
> of the service quality White residents get, it's legally compliant.
> That means Emily could correctly handle Black residents' calls only
> 51% of the time if White residents are at 80% — and still be legal.

Ask: "Does that match what you consider fair?"

(This is where the room will react. The EEOC 4/5ths rule sounds
reasonable as a ratio. It sounds unreasonable as real numbers. Let
them feel that gap.)

**Scenario 4: Their Standard**
> "If White residents' calls are handled correctly 80% of the time,
> what's the minimum percentage for Black residents that you would
> consider acceptable for District 3?"

This is the threshold question. Don't rush it. Let people debate.

#### Step C: Lock the Number (10 minutes)

Facilitate toward a single number or a narrow range. Methods:

- If there's clear consensus: confirm it. "It sounds like the room is
  saying [X]%. Does anyone disagree?"
- If there's a range: "I'm hearing between 85% and 95%. Can we agree
  on 90% as the District 3 standard?"
- If there's disagreement: record the range and note it. "District 3
  set a standard of 85-95%, with the majority favoring 90%."

**Also ask:**
- "Should this standard be the same for all groups — seniors, non-English
  speakers, people with disabilities — or should some groups have a
  higher bar?"
- "Which groups are you most concerned about?" (This becomes priority_groups)

Write the final number(s) on the flip chart. Circle it.

---

### Part 3: Documentation and Commitment (20 minutes)

#### Sign the Standard (10 minutes)

Open your laptop. Enter the data into the system:
- Threshold they chose
- Priority groups they identified
- Favorable outcome definition they agreed on
- Number of participants
- Date, location, facilitator

Generate the one-page Community Fairness Standard. Print it if possible,
or display it on screen and print later.

Read it aloud to the room:

> "This document says that District 3 residents, on [date], in a session
> with [N] participants facilitated by Matt Jackson and sponsored by
> Councilman Benson, set the following fairness standard for AI systems
> operating in District 3: [threshold]. The priority groups identified
> are [groups]. This standard will be reviewed in 6 months."

Ask: "Does this accurately represent what you decided today?"

If yes — Benson signs. You sign as facilitator. Anyone else who wants
to sign can.

#### The Commitment (5 minutes)

Say this directly:

> "This standard means nothing if nobody checks whether it's being met.
> I'm committing to come back in 6 months — [specific month] — with a
> report showing how Emily performed against the standard you set today.
> If it's meeting your standard, great. If it's not, Councilman Benson
> has documented grounds to demand changes from the vendor."

Ask Benson to confirm the 6-month review publicly.

#### Close (5 minutes)

- Thank everyone
- Leave behind: your contact info and a one-paragraph summary of what
  CDF v1.0 is
- Collect the sign-in sheet
- Do NOT pitch FairLens as a product. Today was about them, not you.

---

## After the Session

### Within 24 hours:
- [ ] Enter all data into FairLens system (build_community_config)
- [ ] Generate the formal CDF v1.0 provenance record
- [ ] Email Benson a PDF of the signed Community Fairness Standard
- [ ] Email all participants a thank-you with a copy of what was decided

### Within 1 week:
- [ ] Run available data (HMDA or Emily call data if accessible) through
      FairLens using District 3's threshold vs EEOC default
- [ ] Document the gap — this is your paper's central finding
- [ ] Send Benson a one-page summary: "Here's what your constituents
      decided, and here's what it means for Emily"

### Within 1 month:
- [ ] Begin writing the paper's Validation Study section using real data
- [ ] Start press outreach with the District 3 story

### At 6 months:
- [ ] Return. Present findings. Ask if the standard needs updating.
- [ ] This is the second domino.
