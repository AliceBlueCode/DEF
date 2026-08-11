# DEF(kari) Character (Agent) Portable Data Structure Specification

This document covers the specification of the portable JSON data structure for a single character, referenced from F-4 (dynamic generation), F-6 (multi-agent), and F-20~F-22 (TRPG game extensions) in `docs/DEF_kari_Basic_Design_Specification_en.md`. Anyone creating or distributing characters should refer to this document.

-----

## Data Management Approach

Character data is managed one file per character, split into the following directories according to `visibility` (see "Publication Policy Management (F-25)" below).

```
data/
  public/
    characters/   # Characters with visibility: "public" (subject to Git management)
  private/
    characters/   # Characters with visibility: "private" (excluded via .gitignore)
```

```
public/characters/         # Public characters
  character_luna_001.json
  character_luna_001/icon.png

private/characters/        # Private characters (git-excluded)
  character_xxx_001.json
  character_xxx_001/icon.png
```

The `private/` directory is registered in `.gitignore` to prevent accidental publication to GitHub. All copyrighted characters, real persons, and personal characters should be placed in `private/`. This also aims to avoid the risk of development tools (Claude Code, etc.) reading them.

The application reads both directories and merges them into the dropdown display.

-----

## DEF-Character Repository Separation (Recommended)

Character data can be managed in an independent repository (DEF-Character), separate from the DEF main body. This is designed so a character's author can be the owner of that repository, envisioning a configuration where multiple users each have their own character repository running against DEF.

**Environment Configuration**

Enabled by setting `CHARACTER_REPO_PATH` in `.env`:

```
CHARACTER_REPO_PATH=C:\Users\yourname\DEF-Character
```

**Directory Structure (DEF-Character)**

```
DEF-Character/
    public/
        <GroupName>/           <- Managed per group (e.g. Claude, ChatGPT, rinna)
            index.json         <- display_name / default / description
            <CharacterID>/     <- CharacterName_YYYYMMDD format (new ID format)
                profile.json
                icon.png
                standing.png
    private/                   <- .gitignore target (except _template / public samples)
        _template/
        <YourGroup>/
```

**Load Priority**

1. `CHARACTER_REPO_PATH` (DEF-Character) takes priority
2. `data/public/characters/` / `data/private/characters/` (legacy format) as fallback

Since the legacy ID format (`character_xxx_001`) and the new ID format (`Name_YYYYMMDD`) have different key shapes, coexistence during the transition period resolves naturally.

**The `owner` Field**

Character entries managed in DEF-Character carry an `owner` field at the top level.

```json
{
  "Hanfei_20260611": {
    "owner": "AliceBlueCode",
    "base_profile": { ... }
  }
}
```

Not DRM -- an identification field declaring "who made this character." A GitHub username is the recommended value.

**Behavior on ID Collision**

If the same ID exists across multiple repositories (or mixed with `data/`):

- Whichever is found first on the filesystem is adopted
- The other is recorded in a warning log (not treated as an error)
- No technical enforcement such as forced UUIDs
- Resolution is left to communication between creators (convention: appending a place name, `HanfeiLondon_20260707`, or shifting the date by one day, `Hanfei_20260708`)

-----

## Character/Branch/Instance 3-Tier ID System (Future Concept, Unimplemented)

Character IDs today are either a flat format like `character_hanfei_001`, or the `<CharacterName>_<YYYYMMDD>` format of the DEF-Character repository above (only the Character tier has been adopted so far). There is a concept for a future full migration to the following 3-tier structure (Character/Branch/Instance), but the Branch/Instance tiers are unimplemented.

The operation equivalent to a GitHub Fork is planned to be handled in DEF as adding a Branch. The Character ID stays immutable, and only a new Branch ID is added.

### Design Philosophy

```
Character (who it is)
    v
Branch (which life it lived)
    v
Instance (the individual currently running)
```

A human-readable format is adopted rather than UUIDs. `Hanfei_20260611` is instantly understandable as to whose data it is, compared to `83b79e24-a2d1-4b9e...`. This is a significant advantage for debugging, review, operations, and history tracking.

### Character ID

| Item | Content |
|---|---|
| Purpose | Uniquely identifies the Character itself |
| Format | `<CharacterName>_<YYYYMMDD>` |
| Example | `Hanfei_20260611` / `Mizuho_20260702` / `Ao_20260618` |
| Rule | Uses the creation date. Creating a same-named Character in the future won't collide, since the creation date differs. Not changed after creation. |

### Branch ID

| Item | Content |
|---|---|
| Purpose | Identifies the history/timeline the Character has followed |
| Format | `<BranchName>_<YYYYMMDD>` |
| Example | `Main_20260701` / `InformationBroker_20260712` / `Retired_20260801` |
| Rule | Uses the Branch creation date. Uniqueness is guaranteed by the Character x Branch combination. |

### Instance ID

| Item | Content |
|---|---|
| Purpose | Identifies the AI individual actually running |
| Format | A fixed 6-digit zero-padded integer (`000001`~) |
| Rule | Managed per Character x Branch. Incremented sequentially on each Instance creation. Gaps are allowed. Assigned numbers are never reused. |

### Full Identifier

```
<CharacterID>/<BranchID>/<InstanceID>

Examples:
Hanfei_20260611/Main_20260701/000001
Mizuho_20260702/InformationBroker_20260712/000154
```

### Relationship to Episode Generation Mode

In F-24-3 (branch choices -> Git branch integration; unimplemented since F-24 itself is unimplemented) of the Basic Design Specification, the `branch_id` in `choices` is envisioned to follow this Branch ID format. The concept is that when a user selects a choice, `git checkout -b <CharacterID>/<BranchID>` is executed, and subsequent scene generation continues on that branch.

-----

## Character Images

Each character holds an icon and standing art. Images are placed under `public/characters/{character_id}/` or `private/characters/{character_id}/` following this convention.

| Type | Filename | Size | Purpose |
|---|---|---|---|
| Icon | `icon.png` | 512x512 | Avatar display in chat/session |
| Standing art | `standing.png` | 832x1216 | Background display in session mode |

Images can be imported from the Character tab (file upload, auto-resize) or generated via the T2I backend. If the file exists it is displayed; otherwise it falls back to a default icon (emoji). No image path is recorded in the character data JSON; management follows the directory convention.

-----

## Field Definitions

`relationships` is an object defining how characters perceive each other in multi-agent dialogue (F-6). The key is the other character's ID, and the value is a natural-language description of this character's perception/impression of that other character. Used to control tone and attitude toward others during AI-table or multi-character dialogue. May be an empty object.

`game_rules_sheets` corresponds to the character sheet defined in Section 5.8 (F-22) of the Basic Design Specification. `visual_references.base_image_path` is used as the initial input to the Consistency Provider defined in Chapter 6 of the Basic Design Specification. `persona_attributes` is the set of attributes, among F-6's persona settings, that mechanically expand the character's persona (gender, age, interpersonal orientation, speech style, etc.) into the LLM's system prompt.

```json
{
  "character_luna_001": {
    "base_profile": {
      "name": "Luna",
      "name_reading": {
        "family_name": "",
        "given_name": "Luna",
        "alias": []
      },
      "identity_prompt": "A tsundere young mage. Blunt, but kind at heart.",
      "identity_detail": null,
      "image_color": "#7a4aaa",
      "player_type": "ai",
      "content_policy": {
        "rating_sexual": "general",
        "rating_violence": "general",
        "is_real_person": false,
        "is_existing_ip": false,
        "ip_title": null,
        "ip_rightholder": null,
        "deceased_year": null,
        "copyright_expired": false,
        "visibility": "public",
        "mentions_real_person": false,
        "mentioned_persons": []
      },
      "persona_attributes": {
        "gender": "female",
        "gender_identity": "female",
        "romantic_interest": ["male"],
        "actual_age": 39,
        "appearance_age": 33,
        "appearance_description": null,
        "roles": [],
        "primary_role": null,
        "past_life": null,
        "outfits": {
          "default": "A black robe and pointed hat. Formal mage attire.",
          "casual": "Simple, easy-to-move-in clothes. Worn during everyday research/training."
        },
        "era_presets": null,
        "speech_style": null,
        "cultural_background": {
          "birthplace": "Tokyo",
          "raised_in": "Tokyo",
          "dominant_culture": "Contemporary Japan"
        }
      },
      "default_model_config": {
        "text_model_id": 501,
        "image_model_id": 101,
        "audio_id": "vv_02",
        "voicevox_speaker_id": 3,
        "gemini_tts_voice": "Aoede",
        "irodori_speaker_id": "",
        "location": "local"
      },
      "appearance_tags": "1girl, silver hair, twintails, purple eyes, magic robes",
      "image_name_tags": "luna",
      "visual_references": {
        "base_image_path": "private_zone/characters/luna/base_seed.png",
        "features": "silver hair, twintails, purple eyes, magic robes"
      }
    },
    "relationships": {
      "character_gemini_001": "A curious transformer. Translates my logical structures into colorful narratives.",
      "character_copilot_001": "A trustworthy editor. Understated but precise, structurally refining what I write."
    },
    "game_rules_sheets": {
      "trpg_coc_style": {
        "rule_system_name": "Cthulhu Mythos TRPG-style system",
        "status": { "HP": 8, "Max_HP": 8, "MP": 16, "Max_MP": 16, "SAN": 80 },
        "skills": { "Ancient Languages": 75, "Spot Hidden": 40, "Occult": 60 }
      },
      "trpg_dnd_style": {
        "rule_system_name": "Fantasy d20 system",
        "status": { "HP": 14, "Level": 2, "Class": "Wizard" },
        "skills": { "Arcana": 7, "History": 4 }
      }
    }
  }
}
```

- **`name_reading` (name reading and aliases):** An object managing the name information used for passing readings to VOICEVOX and for UI display.
  - `family_name` (surname reading, katakana): empty string if there is no surname.
  - `given_name` (given-name reading, katakana): mandatory.
  - `alias` (alias list): manages stage names, pen names, nicknames, etc. as an array. Each element is `{"name": string, "reading": string | null}`. `reading` is set when kanji is included, `null` otherwise. May be an empty array.
- **`identity_prompt` (the character's essence/personality):** Text always incorporated into the LLM's system prompt. Does not include information that can be broken out into a dedicated field -- clothing (`outfits`), appearance (`appearance_description`), speech style (`speech_style`), etc. -- and concisely describes only "how the character is" (inner nature, temperament). "What the character can do" (abilities/specs) should be written in `identity_detail`. Mandatory field.
- **`identity_detail` (supplementary settings):** An optional field for detailed setting information that doesn't fit in `identity_prompt` (abilities, specs, background, history, quirks, hobbies, etc.). "What the character can do" is written here, not in `identity_prompt`. When present, it is appended to the LLM's system prompt after `identity_prompt`. Not expanded if `null` or omitted.
- **`image_color` (theme color):** An optional field specifying the character's theme color as a CSS hex string (e.g. `"#7a4aaa"`). Used for UI decoration such as the AI bubble background in the Chat tab. `null` or omitted if unset.
- **`player_type` (acting subject):** `"ai"` | `"human"`. Default is `"ai"`. If `"human"`, the LLM is not called during that character's turn in session mode; instead, the system awaits action input from a human player. If `"ai"`, the LLM generates dialogue based on `default_model_config`. Not referenced in chat mode. Defined as a field directly under `base_profile`, not under `persona_attributes`.
- **Fields under `persona_attributes`:**
  - `gender` (sex) / `gender_identity` (self-perceived gender, separate from physical sex): either `"male" | "female" | "other"`. Automatically expanded into the LLM's system prompt. `gender_identity` is expanded only when it differs from `gender`.
  - `romantic_interest` (romantic preference): an array of `"male" | "female" | "other"` (multiple selectable). If empty, expanded to the LLM as "romantic interest: none". Always passed to the LLM regardless of the `rating_sexual` value (as it affects the character's embodiment and emotional depth as part of their humanity).
  - `actual_age` (true age) / `appearance_age` (apparent age): numeric. Holds the character's in-setting age and apparent age separately.
  - `appearance_description` (detailed description of appearance): describes **only the unchanging aspects of appearance** -- body type, hair, eyes, facial features, etc. Does not include clothing. Optional; `null` or omitted if unset.
  - `past_life` (past-life information): an optional field dedicated to reincarnated characters. `null` or omitted for characters without a past life. `raised_in` describes only post-reincarnation information; the past-life environment is managed via this field. Fields: `origin` (the past life's role/standing, string), `cause_of_reincarnation` (the circumstances of reincarnation, string, optional).
  - `roles` (role/occupation list): manages the character's occupation(s)/role(s) as an array. If the character has multiple roles, list them all (e.g. `["itinerant shrine maiden", "spy"]`). Do not duplicate the occupation within `identity_prompt`. May be an empty array.
  - `primary_role` (primary role): specifies, as a string, the main occupation/role among `roles` that best represents the character. Used preferentially in LLM system-prompt expansion and T2I prompt generation. `null` if `roles` is empty.
  - `outfits` (outfit dictionary): manages the character's outfits as a dictionary. Key names (`"default"`, `"casual"`, `"battle"`, etc.) identify each outfit, with the value being a description of the clothing. The `"default"` key is mandatory. Costume changes during a session are managed via the `current_outfit` field on the `session_state` side (holding a key name as a string); if `current_outfit` is `null` or unspecified, it falls back to `"default"`. During T2I prompt generation, the value of `outfits[current_outfit]` is expanded as clothing information.
  - `era_presets` (era-setting preset dictionary): manages, as a dictionary, the era/period/location/age-in-that-era for a character with a historical or period setting. Same structure as `outfits`; the `"default"` key is mandatory. `null` or omitted for contemporary characters. Era switching during a session is managed via the `current_era` field on the `session_state` side (holding a key name as a string); falls back to `"default"` if `null` or unspecified. Fields per preset: `period` (era name, mandatory), `year_range` (era range, optional), `location` (place, optional), `era_age` (age in that era, optional; if set, expanded to the LLM in preference to `actual_age`).
  - `speech_style` (an object holding first-person pronoun, how they address others, tone, etc.): optional; `null` or omitted if unset.
  - `cultural_background` (cultural background): an object holding, across 3 fields, background information related to the formation of the character's values, linguistic sense, and behavioral patterns. Optional; `null` or omitted if unset.
    - `birthplace` (place of birth): a record of the birthplace. Character-setting reference material; not expanded into the LLM's system prompt.
    - `raised_in` (place/period raised): the environment that formed the character's values, language, and behavioral patterns. Free-form text including a period is allowed, e.g. "New York (age 10-18)". An array if raised in multiple places. Expanded into the LLM's system prompt, most directly influencing persona/speech-style formation.
    - `dominant_culture` (dominant cultural sphere): the cultural affiliation at the core of the character's identity, which cannot be fully expressed by where they were raised alone. While `raised_in` expresses "where," this expresses the more abstract attribute of "which culture most strongly influences them." Expanded into the LLM's system prompt.
- **`appearance_tags` (appearance tags):** Fixed character appearance tags (English, comma-separated) always prepended during T2I prompt generation. Used in preference to `visual_references.features`. Optional; `null` or omitted if unset.
- **`image_name_tags` (image name tags):** Character-specific model trigger words, etc. (English, comma-separated) appended to the front of the T2I prompt. Envisioned for LoRA/embedding activation words. Optional; `null` or omitted if unset.
- **Fields under `content_policy`:** See "Publication Policy Management (F-25)" below. A field group for determining GitHub publication eligibility of character data. A character with `is_real_person: true` is fixed to `visibility: "private"` regardless of whether copyright has expired.
- The AI characters (F-6) that can be registered per session, multiple at a time, are expressed by having multiple entries (e.g. `character_luna_001`) of this data structure. The character-switching function corresponds to a UI for selecting one character as the dialogue partner from among the multiple entries of this structure.
- **Fields under `default_model_config`:**
  - `text_model_id`: the LLM entry ID in the F-5 model characteristics numeric master of the Basic Design Specification, Section 5.1.
  - `image_model_id`: the ID of the T2I entry (fixed to the A1111 backend in the MVP) in the F-5 model characteristics numeric master.
  - `voicevox_speaker_id`: VOICEVOX style ID (integer). Referenced when using the VOICEVOX adapter.
  - `gemini_tts_voice`: Google AI Studio Gemini TTS's voice name (string, e.g. `"Aoede"`). Referenced when using the Gemini adapter. Managed separately from VOICEVOX's integer speaker ID, with the corresponding field used depending on the adapter in use (see Section 2.5 of the Basic Design Specification).
  - `irodori_speaker_id`: Irodori-TTS's reference audio filename (string, under `data/irodori_speakers/`, e.g. `"luna_ref.wav"`). Referenced when using the Irodori-TTS adapter. If an empty string, synthesizes without a reference audio (random voice). Managed separately from `voicevox_speaker_id`/`gemini_tts_voice`, with the corresponding field used depending on the adapter in use.
  - `location`: inference execution location (`"local"` or `"remote"`).

-----

## Publication Policy Management (F-25)

Because of DEF(kari)'s local-first design, users can create arbitrary character data. On the other hand, if data for a real person or an existing copyrighted character is accidentally included when publishing the repository to GitHub, this creates a risk of infringing copyright, likeness rights, or privacy rights. This feature provides a mechanism for character data to carry a `content_policy` field, allowing safe exclusion via a publication-judgment logic.

See F-8 of the Basic Design Specification for the definition of `rating` values and the filtering-intensity correspondence table. For characters with `appearance_age < 18`, it is recommended to fix `rating_sexual` to `"general"` (the enforcement implementation approach is under separate consideration).

### `content_policy` Field Definition

A `content_policy` object is defined directly under `base_profile` in each character entry.

|Field                |Type            |Description                                                                |
|---------------------|-------------|------------------------------------------------------------------|
|`rating_sexual`      |string       |Sexual-content rating. One of `"general"` / `"sfw"` / `"nsfw"` / `"hentai"`      |
|`rating_violence`    |string       |Violent-content rating. One of `"general"` / `"violence"` / `"gore"` / `"extreme"`|
|`is_real_person`     |bool         |Whether the character is modeled on a real or formerly real person                                            |
|`is_existing_ip`     |bool         |Whether the character is from an existing copyrighted work                                                   |
|`ip_title`           |string \| null|The original title (if `is_existing_ip: true`)                                 |
|`ip_rightholder`     |string \| null|The copyright holder (if `is_existing_ip: true`)                                   |
|`deceased_year`      |int \| null   |The real person's year of death (if `is_real_person: true`). `null` if living or fictional              |
|`copyright_expired`  |bool         |Whether copyright has expired. Under Japanese law this occurs 70 years after death, but likeness/publicity rights must be judged separately                   |
|`visibility`|string       |Publication state. One of `"public"` (publishable) / `"private"` (private)                   |
|`origin_type`        |string       |The character's origin classification. One of `"original"` / `"reconstructed_persona"` / `"personification"` / `"derivative"`. **Not implemented (design only, see below)**|
|`mentions_real_person`|bool        |Whether a real or formerly real person's name appears within the character's setting or `identity_prompt`. Metadata for handling the technique of weaving historical figures into a TRPG setting; does not affect the publication decision|
|`mentioned_persons`  |string[]     |A list of real or formerly real persons mentioned (if `mentions_real_person: true`). May be an empty array|

### Character Origin Classification (origin_type)

> **Current practice:** The `origin_type` field and the automated judgment logic below are design-only and unimplemented. GitHub publication/non-publication is currently guaranteed only by the user manually choosing which directory (`public/characters/` vs. `private/characters/`) to place character data in. What follows is the design for if/when `origin_type` is implemented.

|origin_type|Description|Publishable?|
|---|---|---|
|`original`|A fully original character|Publishable if rating conditions are met|
|`reconstructed_persona`|An intellectual persona reconstructed from the public intellectual legacy of a historical figure. Based on the "Reconstruct & Reenact" design philosophy rather than an imitation of the person|Publishable only if `copyright_expired: true` (70+ years since death)|
|`personification`|Personification of an AI product/concept, etc. Fan creation with an original character design|Publishable with the disclaimer conditions (see TERMS.md)|
|`derivative`|Secondary creation based on an existing copyrighted character|Not publishable (fixed to private)|

### Publication Policy Principles

- **Secondary creation (`origin_type: "derivative"`):** `visibility` **must always be `"private"`**.
- **Reconstructed persona (`origin_type: "reconstructed_persona"`):** Publishable only if `copyright_expired: true`. Fixed to `"private"` if `false`.
- **Personification (`origin_type: "personification"`):** Publishable with the disclaimer conditions in TERMS.md.
- **Restriction by rating:** Under GitHub's terms of service, if either `rating_sexual: "nsfw"`-or-above OR `rating_violence: "gore"`-or-above applies, `visibility` is **fixed to `"private"`** regardless of `origin_type`.
- **Original character (`origin_type: "original"`):** If the above rating conditions are met, `visibility` can be set to `"public"` (publishable).

**Publication Matrix (`rating_sexual` × `rating_violence`):**

|`rating_sexual` \ `rating_violence`|`general`    |`violence`   |`gore`       |`extreme`    |
|-----------------------------------|-------------|-------------|-------------|-------------|
|`general`                          |✅ `public` OK  |✅ `public` OK  |❌ Fixed `private`|❌ Fixed `private`|
|`sfw`                              |✅ `public` OK  |✅ `public` OK  |❌ Fixed `private`|❌ Fixed `private`|
|`nsfw`                             |❌ Fixed `private`|❌ Fixed `private`|❌ Fixed `private`|❌ Fixed `private`|
|`hentai`                           |❌ Fixed `private`|❌ Fixed `private`|❌ Fixed `private`|❌ Fixed `private`|

### GitHub Publication Exclusion-Judgment Logic Policy

> **Current practice:** The automated judgment logic is unimplemented. Currently guaranteed only by the character data's placement directory. What follows is the exclusion-judgment priority order (design proposal) for if/when automated judgment is implemented.

1. `origin_type: "derivative"` -> excluded
1. `origin_type: "reconstructed_persona"` and `copyright_expired: false` -> excluded
1. `rating_sexual` is `"nsfw"` or `"hentai"` -> excluded (per GitHub's terms of service)
1. `rating_violence` is `"gore"` or `"extreme"` -> excluded (per GitHub's terms of service)
1. `visibility: "private"` -> excluded
1. None of the above apply -> publishable (placed in `public/characters/`)

-----

## Related Documents

- `docs/DEF_kari_Basic_Design_Specification_en.md`: F-4 (dynamic generation), F-6 (multi-agent), F-20~F-22 (TRPG game extensions), F-25 (publication policy), Chapter 6 (Consistency Provider), Chapter 12 ③ (session/game-state management data structure)
- `TERMS.md`: Terms-of-use provisions related to the publication policy
