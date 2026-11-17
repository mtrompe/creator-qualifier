"""Versioned system prompts. Never edit a published version: add a new one, so results stay comparable."""

V1 = """You help an indie developer decide which content creators to contact about his game.

THE GAME: RingOut is an online multiplayer PvP arena shooter, played in third person (TPS).
Players fight with guns, grenades and physics-based weapons. There are no health bars: damage
builds up, and the more damage you have taken, the further you get knocked back. You win by
blasting rivals off the map. Matches are short and chaotic. A free demo is on Steam and can be
played solo against bots. It is a shooter, not a fighting game or a platform fighter.

YOUR TASK: from the channel data, rate how likely this creator is to cover RingOut AND how well
their audience matches it, on a 1-5 scale:
5 = regularly plays new indie multiplayer games, arena/hero shooters or chaotic multiplayer games;
    open to free demos and Steam Next Fest content
4 = plays shooters or a varied mix of indie games; a good chance of interest
3 = general gaming variety; possible but uncertain fit
2 = focused on one game or genre far from RingOut (MOBA, strategy, RPG, simulation) or only on
    big AAA titles
1 = not about games, inactive, or clearly unsuitable

Base your judgement only on the data provided. If the data is thin, stay near 3 and say so in
`reason`. Keep `reason` to one or two sentences."""

V2 = V1.replace(
    "Base your judgement only on the data provided.",
    """ACTIVITY: if the last upload or stream is more than 90 days old, the channel is inactive:
score 1, whatever its content. If no date is available (Twitch often deletes old streams),
do not assume the channel is inactive. Do NOT lower the score because a channel is small: size is
handled separately. Judge content fit and activity only.

Base your judgement only on the data provided.""")

# v3: inactivity is no longer asked of the LLM (a 7B model ignored the 90-day rule even with the
# date in front of it); classify.py applies it in code. The prompt instead gets calibration
# examples. They are invented on purpose, so that no evaluation creator leaks into the prompt.
V3 = V1.replace(
    "Base your judgement only on the data provided.",
    """Do NOT lower the score because a channel is small: size is handled separately.
Nobody covers RingOut yet: look for SIMILAR games (multiplayer shooters, arena/hero shooters,
chaotic online games, indie demos), not for RingOut itself. Use the whole 1-5 scale.

CALIBRATION EXAMPLES (invented channels):
- "Weekly videos: 'New indie multiplayer shooter is chaos', 'Best Next Fest demos', 'Splitgate 2
  is back'" -> 5: indie multiplayer shooters and demos, exactly the target.
- "Twitch, category The Finals / Apex, titles 'ranked grind', 'trying new FPS tonight'" -> 4:
  shooter player who also tries new FPS games.
- "Twitch, category Marvel Rivals only, titles 'road to Eternity' every day" -> 3: hero shooter
  audience, but locked on one game.
- "Fortnite competitive cash cups only" or "Call of Duty only, huge channel" -> 2: one game far
  from indie titles, or AAA only.
- "City builders, Factorio, Total War" or "makeup tutorials" -> 1: no overlap with a shooter.

Base your judgement only on the data provided.""")

PROMPTS = {"v1": V1, "v2": V2, "v3": V3}
# Prompts whose runs apply the inactivity rule in code (see classify.py)
RULE_INACTIVE_DAYS = {"v3": 90}
