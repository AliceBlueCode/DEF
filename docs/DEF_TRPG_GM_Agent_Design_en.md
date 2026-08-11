# DEF TRPG GM Agent System Design

This document covers the design of the multi-agent system that runs on top of TRPG mode. Built on DEF's existing infrastructure (`session.py`, `characters.py`, etc.), it defines and extends the GM, Player, and NPC roles as Agents.

**Goal**: build a foundation where AI alone can complete a TRPG session. It works whether or not a human participates.

-----

## 1. Design Philosophy

### Character Authenticity over Human Imitation

This system does not aim for the AI to imitate a human. The evaluation axis is not "how human-like," but:
- Can it behave consistently as that character?
- Is it consistent with the setting/world?
- Is its judgment internally consistent?

**Being an AI is not a flaw -- it is treated as one personality trait among others.**

### Character First

What this project handles is not "imitation of a human" but a "persistent character." A character can be human, AI, a fictional being, or a real person's public persona. What matters is **being natural as that character**.

### Character ≠ Agent (Most Important)

**Agent and Character are different things.** Do not conflate them.

```
Character (a persistent entity)
    v owns
Agent Instance (a role/behavior type)
    v runs on
Runtime: LLM | Human | Rule (swappable)
```

- **Character** = the persistent entity defined by `profile.json`. Holds a persona, appearance, values, and memory.
- **Agent** = an instance of "what role" that Character is playing (Player / NPC / Observer).
- **Runtime** = the actual entity driving it. Swappable between an LLM, a human, or a rule engine.

This design means:
- Whether the same character is operated by a human or by a different model, the Character itself doesn't change.
- Even as AI evolves or services change, the character persists.
- This is the concrete implementation of DEF's "Characters persist longer than conversations."

**Only the GM Agent is special.** It does not own a specific Character, and functions as an administrator Agent managing the World/Story/NPCs/Director.

-----

## 2. Architecture

### Layer Structure

```
Application Layer
└── Game Manager

Agent Layer
├── GM Agent                  <- Character-independent administrator
├── Player Agent x N          <- owned by each Character
├── NPC Agent x N              <- owned by each Character
└── Observer Agent (future)   <- Character-independent observer

Service Layer
├── Context Builder
├── Event Bus
├── Rule Engine
└── Dice Engine

Domain Layer
├── Character
├── World
├── Story / Campaign
├── Quest
├── Memory
└── Relationship

Infrastructure Layer
├── LLM Backend
├── History Store
├── JSON Storage
└── Session API
```

### The Character -> Agent -> Runtime Relationship

```
hanfei_20260611 (Character)
    └── Player Agent
            └── Runtime: LLM (local model)

Father Joseph (Character / NPC)
    └── NPC Agent
            └── Runtime: LLM

Human Player (Human)
    └── Player Agent
            └── Runtime: Human (waiting_for_human)

GM Agent
    ├── World Manager
    ├── Story Manager
    ├── NPC Controller
    ├── Director
    └── Runtime: LLM
```

**Only the Game Manager talks directly to players (human/AI).**

-----

## 3. Agent Interface

The common interface implemented by every Agent:

```python
class Agent:
    def perceive(self, context: dict) -> None:
        """Receives the current situation/events"""

    def think(self) -> list[str]:
        """Generates candidate actions based on goals, memory, and personality"""

    def act(self) -> AgentResult:
        """Decides on and returns an action/utterance"""

    def reflect(self, result: AgentResult) -> None:
        """Reflects the experience into memory"""
```

```python
@dataclass
class AgentResult:
    message: str          # The utterance/action text
    state_update: dict    # State changes
    events: list[str]     # Names of events to fire
    confidence: float     # 0.0-1.0
```

What differs between GM and Player is **only which responsibilities they hold**. The framework is shared.

| Function | GM Agent | Player Agent | NPC Agent |
|------|----------|--------------|-----------|
| World management | v | x | x |
| NPC operation | v | x | x |
| Rule adjudication | v | x (requests only) | x |
| Controls own character | x | v | v |
| Party consultation | x | v | x |
| Scenario progression | v | x | x |

-----

## 4. GM Agent

A special administrator Agent that does not own a Character. Tracks the rulebook, scenario, world setting, and the state of all NPCs, and advances the session. Implemented in `def_kari/gm/gm_agent.py`.

### Internal Sub-Responsibilities

| Responsibility | Description |
|------|------|
| World | Tracks and describes locations, environment, and world state |
| Story | Manages Campaign/Chapter/Scene/Flags and controls progression |
| Rule | Adjudicates whether a check is needed and its result, per the rulebook |
| Director | Handles staging, atmosphere, and guiding toward the next scene |
| GM Planner | Controls the next event, NPC entrance timing, and climax pacing |

### The Truth Only the GM Knows

As a design principle of the Context Builder, the GM holds "all information." Player Agents are given only "what that character knows." This creates the information asymmetry that makes it a game.

```
GM: { "truth": "The priest is a vampire" }
PlayerA: { "knowledge": ["The priest seems suspicious"] }
PlayerB: { "knowledge": [] }   <- knows nothing
```

### Context Composition

```
System: the Keeper's role definition
Rulebook: judgment criteria, world setting
Scenario: current scene, goals, flag state (GM-only)
Character info: participant list, name map
History: the most recent N turns
```

### AI Keeper Assignment and Persona Installation (F-21)

- "AI Keeper" is selected in the Keeper setting at session start
- Character assignment is optional. If unassigned, it runs in **anonymous mode** (mechanical progression text only)
- An assigned character does not enter the participants' initiative
- Once assigned, the Keeper is voiced with that character's persona and speech style (a design that first secures "working as a function," then layers "who is performing it" on top)

**Responsibilities of the AI Keeper:**
- Gives top priority to the rulebook (F-20)
- Scene description and progression (situational description following the rules)
- Requesting dice rolls and reacting to judgment results (describing success/failure)
- Presenting `choices` and progressing the branch after selection

### Relationship to Safety (F-8)

If the AI Keeper's scene descriptions (e.g. "there is a bloodstain," "the body...") get fully masked by F-8, progression stalls.
-> Keeper-layer speech is treated as equivalent to `warn`, with a guardrail to prevent it from becoming `mask`.

-----

## 5. Player Agent

An Agent owned by a Character. Reads persona and values from the Character's `profile.json`, and makes decisions based on Goal/Emotion/Memory. Implemented in `def_kari/gm/player_agent.py`.

### Internal Structure

```
Player Agent
├── Personality   <- read from the Character's profile.json (setting)
├── Character Sheet <- game_rules_sheets (HP/MP/skills, etc.)
├── Goal          <- 3 tiers (ultimate goal / current / immediate)
├── Emotion       <- Fear / Trust / Anger / Hope / Stress (dynamic)
├── Memory        <- read from the Character's memory/ (experience)
├── Knowledge     <- what the character knows (including info other PCs don't)
├── Planner       <- generates action candidates -> scores by Emotion -> decides
└── Dialogue      <- converts the action into roleplay speech
```

### The 3-Tier Goal

```json
{
  "ultimate": "Survive",
  "current": "Go to the temple",
  "immediate": "Question the priest"
}
```

When a lower-tier Goal is achieved or abandoned, the next `immediate` is generated from the tier above.

### Decision-Making Flow

```
GM's description
  -> Understanding the situation (perceive)
  -> Checking Goal / referencing Memory (think)
  -> Generating action candidates
  -> Scoring by Emotion
  -> Deciding (act)
  -> Generating Dialogue
  -> Sending
  -> reflect (adding the experience to Memory)
```

### Planner Stages

- **Static Planner**: Goal is held in `profile.json`; candidates are chosen via rule-based scoring on Emotion values
- **LLM Planner**: when enabled via settings, a small LLM call is added to the Planner to dynamically generate candidates

-----

## 6. NPC Agent

An Agent owned by a Character. Has the same structure as a Player Agent, but lacks party-consultation functionality.

Additional fields it carries (Goal/Knowledge/Relationship):
```json
{
  "goal": { "immediate": "Leave without giving the investigators any information" },
  "knowledge": ["Knows the basement exists"],
  "relationship": { "hanfei_20260611": { "trust": 20, "hostility": 60 } }
}
```

An NPC's Knowledge/Relationship is updated dynamically during a session (`session["npc_state"]`).

-----

## 7. Observer Agent (Future Concept, Unimplemented)

An Agent that observes and records from outside the session, without participating. Does not own a Character.

### Role and Episode Integration

```
TRPG Session
    v Observer observes and records
Episode (novel material)
    v Written up in Novel mode
Novel
```

The intent is for this to function not as "a summary of each scene," but as **a character's life record**. The ideal is for events from a TRPG session (failures, heroics) to naturally come up as conversation topics in Chat mode.

Role:
- Extracting per-scene highlights and emotional beats
- Recording character growth
- Generating replay material after a session
- Integration with DEF's "Episode" (novel-writing) mode

Because this concept **connects directly to DEF's core values**, the design has been worked out early even though implementation is a future phase.

### Continuity Between TRPG Sessions and Chat Sessions

What happens in a TRPG session persists as the character's memory and experience.

- An AI character can bring up, in a Chat session, an experience it lived through -- "back in that scenario, when XYZ happened..."
- The TRPG adventure becomes part of what constitutes the character's persona, relationships, and memory
- This connects directly to DEF's design philosophy that "a character is not merely a chat history"

At the implementation level, this needs a mechanism to reflect a TRPG session's log into the character's memory under `memory/episodic/`, which the Observer Agent is expected to handle.

-----

## 8. Service Layer

### 8.1 Context Builder

`def_kari/gm/context_builder.py` implements a set of functions that hand different information to the GM, Player, and NPC respectively.

**Design principle**: minimize the information handed to an Agent. Handing over all information turns it into "an AI with omniscient view of the world."

#### Interface Design

```python
class ContextBuilder:

    def build_for_gm(self, rulebook, scenario, session, user_lang) -> str:
        """GM context.
        - Full scenario information (including gm_notes / goal / gm_only flags)
        - All character sheets (HP/MP/SAN, etc.)
        - Current flag state (including gm_only flags)
        - World state
        """

    def build_for_player(self, char_id, character, rulebook, scenario, session, user_lang) -> str:
        """Player context.
        - Only the current scene's description (gm_notes excluded)
        - Only public NPCs' description (gm_notes / goal excluded)
        - Only their own character sheet
        - Their own knowledge (static: from profile.json + dynamic: acquired during the session)
        - gm_only: false flags relevant to them
        """

    def build_for_npc(self, npc_id, npc_data, rulebook, scenario, session, user_lang) -> str:
        """NPC context.
        - Their own goal (visible to the NPC)
        - Their own knowledge
        - Relationship toward PCs (trust / hostility)
        - Public scene information
        """
```

#### Scenario JSON Schema Extension

To realize information asymmetry, the scenario side carries `gm_notes` / `gm_only` fields:

```json
{
  "scenes": [{
    "id": "scene_1",
    "title": "Entrance Hall",
    "description": "The entrance hall of an old mansion. A butler greets you.",
    "gm_notes":   "The butler's right hand trembles faintly. A sign of demonic possession.",
    "npcs":       ["butler_johnson"]
  }],
  "npcs": [{
    "id":          "butler_johnson",
    "name":        "Butler Johnson",
    "description": "A courteous old man",
    "gm_notes":    "Sold his soul to a demon. Flees if found out.",
    "goal":        "Lure the players into another room"
  }],
  "flags": [
    { "key": "found_secret_door",   "value": false, "gm_only": false },
    { "key": "butler_is_possessed", "value": true,  "gm_only": true  }
  ]
}
```

Rules:
- `description` -> visible to everyone
- `gm_notes` / `goal` / a `gm_only: true` flag -> GM-only (not passed to Player/NPC)

When a `gm_only: false` flag is updated during a session, it is appended to that character's "what they know" (`session["player_knowledge"]`), via the Event Bus's `FLAG_UPDATED` handler. Static knowledge (known from the start of the session) lives in the `knowledge` field of `profile.json`.

### 8.2 Event Bus

`def_kari/gm/events.py` implements the event bus for game logic (a separate namespace from `core/events.py`, which is dedicated to TTS/image completion notifications).

```python
# Game logic events
NPC_DEAD         = "npc_dead"
FLAG_UPDATED     = "flag_updated"
QUEST_STARTED    = "quest_started"
QUEST_COMPLETED  = "quest_completed"
DAMAGE_APPLIED   = "damage_applied"
STATUS_CHANGED   = "status_changed"
SCENE_CHANGED    = "scene_changed"
```

Example chain:

```
Player Attack
  -> Rule Engine (damage calculation)
  -> DAMAGE_APPLIED event
  -> NPC Agent (HP update)
  -> NPC_DEAD event (if HP<=0)
  -> Story Manager (flag update)
  -> FLAG_UPDATED event
  -> Observer (recording)
  -> Director (staging)
```

Multiplayer support (see `docs/DEF_kari_Multiplayer_API_Reference_en.md`) is realized by adding subscribers to this same Event Bus.

### 8.3 Rule Engine

Implemented in `def_kari/trpg/rule_engine.py`.

**Design principle**: rule interpretation (success/failure judgment) is **never left to the LLM**. Code handles it deterministically. The LLM is not the adjudicator -- it is the narrator.

```
Bad design: Player -> LLM "The attack succeeded"
Good design: Player -> Rule Engine (success/failure) -> LLM "How to stage it"
```

Differences between game systems are absorbed by the rulebook JSON (see `docs/DEF_TRPG_Rulebook_en.md`).

### 8.4 Dice Engine

Implemented as `POST /api/trpg/dice`. Generates secure random numbers via `secrets.randbelow()`. Supports `NdM±K` notation (see `docs/DEF_Glossary_en.md` for details).

-----

## 9. Domain Layer

### Character

Composed of DEF Character's `profile.json` and a `memory/` directory.

**Important**: `profile.json` is "setting," `memory/` is "experience." Do not mix them.

```
Character/
├── profile.json       <- persistent persona, appearance, values (setting)
└── memory/
    ├── episodic/      <- memories of events ("failed at XYZ back then")
    ├── knowledge/     <- acquired knowledge ("knows the basement exists")
    └── relationship/  <- relationships/emotional values (dynamically updated)
```

What goes in `profile.json`: name / personality / speech_style / appearance / base_values
What goes in `memory/`: experience, acquired information, emotional shifts

### Goal and Emotion (Dynamic In-Session Data)

Since Goal and current Emotion change during a session, they are held as session state, and recorded to `memory/episodic/` after the session ends.

```json
{
  "goal": { "ultimate": "Survive", "current": "Go to the temple", "immediate": "Question the priest" },
  "emotion": { "fear": 20, "trust": 60, "anger": 10, "hope": 70, "stress": 30 }
}
```

### World / Story / Campaign

`def_kari/gm/domain.py` defines dataclasses for `World` / `WorldNPC` / `WorldLocation` / `Story` / `StoryScene` / `Campaign`. The intent is to manage them in a Campaign -> Chapter -> Scene -> Flags hierarchy, but persistence and directory structure are not yet fleshed out.

### Rulebook/Scenario Data Placement (F-20)

```
data/public/trpg_rules/      <- public rulebooks/scenarios (subject to Git management)
data/private/trpg_rules/     <- NSFW rulebooks/scenarios (gitignored)
```

The file format must be JSON (since the Rule Engine parses it). See `docs/DEF_TRPG_Rulebook_en.md` for the detailed schema.

Selecting a rulebook/scenario from the dropdown at session start expands the JSON into the system prompt. If none is selected, it behaves the same as a normal session.

### Persisting Character Sheets

The `game_rules_sheets` field is persisted into the character's `profile.json`.

- Multiple `game_rules_sheets` can be held across rule systems (for CoC, for DEF's original system, etc.)
- Skill allocation and current stat values persist across sessions
- Which rule sheet to use is selected at session start

-----

## 10. Implementation Status

| Design Concept | Status | Location |
|---------|----------|------|
| Game Manager | Implemented | `session.py` (throughout) |
| GM Agent | Implemented | `gm/gm_agent.py` |
| Context Builder (GM/Player/NPC separation) | Implemented | `gm/context_builder.py` |
| Turn control / Initiative | Implemented | `session.py: start_session()` / `next_turn()` |
| Human/AI mixing (equivalent to Runtime swapping) | Implemented | `player_type == "human"` |
| Party Coordinator | Implemented | `vote_deliberate()` / `vote_commit()` |
| Director (designation) | Implemented | `designate_next()` |
| Rule Engine | Implemented | `trpg/rule_engine.py` |
| Dice Engine | Implemented | `api/routes/trpg.py: dice_roll()` |
| Event Bus (for game logic) | Implemented | `gm/events.py` |
| World / Story / Campaign data model | Implemented (persistence not yet built out) | `gm/domain.py` |
| Player Agent Goal (static) | Implemented | `profile.json > goals` |
| Player Agent Planner (LLM) | Implemented (enabled via settings) | `gm/player_agent.py` |
| NPC Knowledge / Relationship dynamic update | Implemented | `session.py: npc_state` |
| Memory separation (profile vs. experience) | Implemented | `gm/memory.py: episodic` |
| In-session player_knowledge management | Implemented | `session.py: player_knowledge` |
| Scenario JSON gm_notes / gm_only extension | Implemented | `context_builder.py` |
| Damage table, scenario-linked damage, dead-view mode | Implemented | See `docs/DEF_TRPG_Rulebook_en.md` for details |
| Online multiplayer | Implemented | See `docs/DEF_kari_Multiplayer_API_Reference_en.md` for details |
| Observer Agent | Not implemented (future concept) | -- |
| Migrating `relationship` into `memory/` | Not started (currently co-located in `profile.json`) | -- |
| F-22-Git branching by timeline | Not implemented (future concept, see Chapter 11 below) | -- |

-----

## 11. F-22-Git Branching by Timeline (Future Concept)

- Selecting a choice from `choices` branches via `git checkout -b <branch_id>`
- Never merges (same policy as the DEF-Character repository -- timelines continue to exist independently)
- After branching, progression continues on that branch
- The UI shows "the current timeline"

**Technical challenge**: a `git checkout -b` during a live session affects the backend process and filesystem state. The risk of branching while a session is running needs further consideration.

-----

## 12. UI Concept

### Additions to the Session Tab

```
[ > Start ]

TRPG Mode: [OFF / ON]
  └── Rulebook: [---- Select ----]
  └── Scenario: [---- Select ----]
  └── AI Keeper: [---- Don't assign ----]

[ Dice ]  Notation: [1d100    ]  [ Roll ]
```

### Dice Roll Result (in the Chat Log)

```
Spot Hidden: 1d100 -> 37 (Success: judgment value 55)
```

-----

## Related Documents

- `docs/DEF_kari_Basic_Design_Specification_en.md`: F-20~F-22 (TRPG game extensions)
- `docs/DEF_TRPG_Rulebook_en.md`: The rulebook JSON schema, judgment formulas, and damage table
- `docs/DEF_TRPG_Table_Autonomy_Rules_en.md`: Speech power, voting, and other autonomy rules
- `docs/DEF_kari_Multiplayer_API_Reference_en.md`: The online multiplayer protocol
- `docs/DEF_Glossary_en.md`: Terminology definitions
