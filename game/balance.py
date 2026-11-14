"""Game balance: all tunable mechanics constants in one place.

Stat rates are per hour of real time; decay is applied lazily by engine.tick()
against the wall clock, so the pet degrades even while nobody is watching.
"""

# Decay / regen per hour
HUNGER_DECAY_PER_HOUR = 6.0
HUNGER_DECAY_SLEEP_PER_HOUR = 9.0
ENERGY_REGEN_SLEEP_PER_HOUR = 10.0
ENERGY_DECAY_PER_HOUR = 4.0
MOOD_DECAY_PER_HOUR = 4.0
MOOD_EXTRA_DECAY_PER_HOUR = 4.0  # added on top while satiety < LOW_STAT_THRESHOLD

LOW_STAT_THRESHOLD = 25.0

# Actions
FEED_SATIETY_GAIN = 25.0
HATCH_MOOD_GAIN = 10.0
PLAY_MOOD_GAIN = 18.0
PLAY_ENERGY_COST = 10.0
PLAY_MIN_ENERGY = 10.0
PET_MOOD_GAIN = 6.0
PET_COOLDOWN_SECONDS = 60

# Progression
TEEN_AFTER_DAYS = 3.0
ADULT_AFTER_DAYS = 7.0

# Notifications
HUNGRY_NOTIFY_AT = 20
HUNGRY_NOTIFY_EVERY_SECONDS = 12 * 3600

# Safety
MAX_OFFLINE_SECONDS = 48 * 3600  # decay cap: a long absence must not be fatal

# Limits
NAME_MAX_LEN = 16

STAGE_NAMES = ('Яйцо 🥚', 'Малыш 🐣', 'Подросток 😼', 'Взрослый 😺')
