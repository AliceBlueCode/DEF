# DEF Glossary v2.1.1

## Overview

DEF has three timelines, each with distinct responsibilities:

- System Time
- Creative Time
- AI Table Time

Each timeline is managed independently.

---

# 1. System Time

## Cycle

The smallest processing unit in DEF.

In one Cycle, a sequence of processing is performed from input through AI processing to output generation.

Processing structure:

```
Input
 ↓
AI Process
 ↓
Output
```

Types of Output:

- Speech (text)
- Image (image)
- Command (system command)

Cycle is a concept representing internal processing time within DEF, and is independent of Creative Time and AI Table Time.

---

# 2. Creative Time

## Episode

An entire work, or a large narrative unit.

Examples:

- Part One
- An entire long-form work
- A major division of a larger story

---

## Chapter

A chapter-level unit that constitutes an Episode.

---

## Scene

A scene-level unit within a narrative.

Represents a sequence of events sharing a common location, time, purpose, etc.

---

## Creative Time Hierarchy

A narrative is structured in three hierarchical levels: Episode > Chapter > Scene. Scene is the smallest structural unit, and the writer determines boundaries by inserting markers in the UI.

```
Episode
 ↓
Chapter
 ↓
Scene
```

---

# 3. AI Table Time

## Session

The largest unit representing an entire AI Table.

Examples of retained information:

- Participants (AI and human)
- Role settings
- World settings
- Initial state
- Speech Counter settings
- Topic (subject, agenda, scenario name, etc.)

The Topic is set by the Keeper, not chosen by the participants.

---

## Scene

The current narrative scene shared among AI participants.

Conceptually corresponds to Scene in Creative Time.

---

## Round

A unit in which every participant is given one opportunity to speak, cycling through all of them.

When all participants' Turns have ended, the Round ends.

---

## Turn

An opportunity to act given to a single participant.

"My Turn!"

That is the unit.

During a Turn, a participant can choose to:

- Speak
- Skip (counter +1)
- Extend Turn (counter -1; allows speaking for one more consecutive Turn)
- Redo (discard accumulated dialogue)

The acting agent for a participant is determined by the character data's `player_type`.

- `player_type: "ai"` -- The LLM sequentially generates speech for the number of Actions
- `player_type: "human"` -- The human player accumulates Actions and confirms with "Done Speaking"

During the execution of a Turn, one or more Cycles occur as needed.

However, Turn does not encompass Cycle as a concept.

Turn is the right to act within the game, while Cycle is an internal processing unit within DEF.

They exist on different timelines, and Cycles occur in order to carry out the processing of a Turn.

---

## Action

An individual speech within a single Turn. The smallest speech unit at the AI Table.

The number of Actions per Turn is configurable (default 2, range 1-5).

With an Action count of 1, the behavior is the same as the traditional 1 speech per Turn.
With an Action count of 2 or more, each Action is given a directive based on the Action Directive Set.

The Action Directive Set is externally managed in `data/public/action_directives/*.json` (1 set per file) and can be switched from the settings tab. NSFW variants are managed in `data/private/action_directives/`.

Hierarchy:

```
Session
 ↓
Scene
 ↓
Round
 ↓
Turn
 ↓
Action
```

---

# 4. Speech Counter

A resource that manages speaking rights at the AI Table.

Each Session participant holds their own. The Keeper does not hold a Speech Counter.

The current counter value is displayed next to each participant's name in the Initiative order display on the Session UI.

---

## How to Gain (+1)

### Voluntary Skip

The participant does not speak during their Turn.

They receive one Speech Counter as a reward.

---

### Forced Skip by Keeper

When the Keeper decides to skip a participant's Turn.

The participant receives one Speech Counter as compensation.

---

### Forced Skip When Counter Is Negative

If the counter is negative, the participant is forced to skip when their Turn comes around.

Even during a forced skip, the counter is incremented by +1, allowing natural recovery.

Example: Counter -1 -> Forced Skip -> +1 -> Counter 0 -> Can speak in the next Round

---

## How to Use (-1)

By spending one Speech Counter, a participant can perform the following:

- Interrupt Speech (-2; speak regardless of speaking order. The cost of 2 prevents a net-zero outcome when combined with Skip +1)
- Designate Next Speaker (after the designated participant finishes speaking, the order returns to normal)
- Extend Turn (allows speaking for the next Turn consecutively)

After the additional Turn ends, the original speaking order resumes.

### Who Performs Counter Operations

| Operation | Performer | Notes |
|---|---|---|
| Voluntary Skip | Player | Regardless of human/AI |
| Forced Skip | Keeper | Target's counter +1 |
| Interrupt / Designate Next Speaker / Extend Turn | Player | Consumes counter as a resource |

---

## Penalty

If the same speech is repeated 3 times, the Speech Counter is decremented by -1.

---

# 5. Speech Counter Limits

## Upper Limit

Configurable.

Recommended value:

3-5

Purpose:

- Prevent excessive accumulation of speaking rights
- Prevent monopolization by a specific participant

---

## Lower Limit

If the Speech Counter is negative, the participant is forced to skip during their Turn.

Even during a forced skip, the counter is incremented by +1, so it naturally recovers to 0 and the participant can speak again.

---

# 6. Keeper

The entity that manages the AI Table. Handles Session progression and adjudication.

The Keeper and human players are separate concepts. The Keeper is an invisible adjudicator who controls the Session from outside, while human players speak as participants within the Session.

In anticipation of future replacement by an AI Keeper (an automatic adjudicator as an invisible logic layer), the Keeper UI and human player UI are implemented independently.

Primary roles:

- Session management
- Scene management
- Round progression
- Turn management
- Speaking order management
- Forced Skip
- Speech Counter management
- Intervention in abnormal states
- Maintaining world settings

The Keeper exists not to exclude participants, but to maintain a fair creative environment.

---

# 7. Design Philosophy

DEF does not aim to generate a single correct answer from a single AI.

It is a space where multiple AIs, each with distinct personalities, perspectives, and philosophies, participate fairly in creative work under common rules.

Humans also participate under the same rules as `player_type: "human"`.

Rules do not exist to take away freedom.

They are the foundation for all participants to engage fairly in the narrative.

"A game without rules is not fair."

This philosophy is the core principle of the DEF AI Table.

---

Document:
DEF_Glossary

Version:
2.1.1

Status:
Release
