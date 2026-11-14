"""Game balance: all tunable mechanics constants in one place.

Stat rates are per hour of real time; decay is applied lazily by engine.tick()
against the wall clock, so the pet degrades even while nobody is watching.
By design there is NO death: a neglected pet gets care misses and an ugly
adult branch, but never runs away or dies.
"""

# --- stat decay / regen per hour ---
HUNGER_DECAY_PER_HOUR = 6.0
HUNGER_DECAY_SLEEP_PER_HOUR = 9.0
ENERGY_REGEN_SLEEP_PER_HOUR = 10.0
ENERGY_DECAY_PER_HOUR = 4.0
HYGIENE_DECAY_PER_HOUR = 4.0
MOOD_DECAY_PER_HOUR = 4.0
MOOD_EXTRA_DECAY_PER_HOUR = 4.0   # added while satiety < LOW_STAT_THRESHOLD
SICK_MOOD_EXTRA_PER_HOUR = 6.0
SICK_ENERGY_EXTRA_PER_HOUR = 6.0

LOW_STAT_THRESHOLD = 25.0

# --- actions ---
HATCH_MOOD_GAIN = 10.0
PLAY_MOOD_GAIN = 18.0
PLAY_ENERGY_COST = 10.0
PLAY_MIN_ENERGY = 10.0
PET_MOOD_GAIN = 6.0
PET_COOLDOWN_SECONDS = 60
CLEAN_COOLDOWN_SECONDS = 300
CLEAN_COINS = 2
SCAVENGE_SATIETY = 10.0           # /feed with empty inventory and no coins
SCAVENGE_COOLDOWN_SECONDS = 180   # foraging is limited to once per 3 minutes

# --- economy ---
START_COINS = 30
START_APPLES = 3
SLEEP_COINS_PER_HOUR = 3.0        # pet earns while sleeping
STREAK_BONUS_BASE = 10            # first day
STREAK_BONUS_STEP = 5             # each consecutive day
STREAK_BONUS_CAP_DAYS = 10        # bonus stops growing after N days
REF_BONUS = 50                    # both referrer and invitee

SHOP = {
    'apple':   {'price': 5,  'title': '🍎 Яблоко',    'kind': 'food'},
    'fish':    {'price': 10, 'title': '🐟 Рыбка',     'kind': 'food'},
    'cake':    {'price': 15, 'title': '🍰 Торт',      'kind': 'food'},
    'med':     {'price': 20, 'title': '💊 Лекарство', 'kind': 'med'},
    'bow':     {'price': 30, 'title': '🎀 Бантик',    'kind': 'accessory'},
    'scarf':   {'price': 35, 'title': '🧣 Шарф',      'kind': 'accessory'},
    'glasses': {'price': 40, 'title': '🕶 Очки',      'kind': 'accessory'},
    'hat':     {'price': 50, 'title': '🎩 Шляпа',     'kind': 'accessory'},
}
FOOD_EFFECTS = {
    'apple': {'satiety': 25.0},
    'fish':  {'satiety': 30.0, 'energy': 5.0},
    'cake':  {'satiety': 40.0, 'mood': 10.0},
}
FOOD_PRIORITY = ('cake', 'fish', 'apple')  # what plain /feed consumes first

# --- sickness (no death: a sick pet auto-recovers after SICK_AUTO_HEAL_HOURS) ---
SICK_CHANCE_DIRTY_PER_HOUR = 0.10   # while hygiene < LOW_STAT_THRESHOLD
SICK_CHANCE_STARVE_PER_HOUR = 0.05  # while satiety < LOW_STAT_THRESHOLD
SICK_CHANCE_BASE_PER_HOUR = 0.003   # ambient background chance
SICK_AUTO_HEAL_HOURS = 24.0         # + 1 care miss

# --- progression ---
TEEN_AFTER_DAYS = 3.0
ADULT_AFTER_DAYS = 7.0
# adult branch at teen -> adult: care_miss == 0 -> wise,
# else care_score >= CARE_MISS_PENALTY * care_miss -> beauty, else hooligan
CARE_MISS_PENALTY = 3

STAGE_EGG, STAGE_BABY, STAGE_TEEN = 0, 1, 2
STAGE_ADULT_WISE, STAGE_ADULT_BEAUTY, STAGE_ADULT_HOOLIGAN = 3, 4, 5
STAGE_NAMES = ('Яйцо 🥚', 'Малыш 🐣', 'Подросток 😼',
               'Мудрец 🎓', 'Красавец ✨', 'Хулиган 😈')

# --- notifications ---
HUNGRY_NOTIFY_AT = 20
HUNGRY_NOTIFY_EVERY_SECONDS = 12 * 3600
SICK_NOTIFY_EVERY_SECONDS = 8 * 3600

# --- safety ---
MAX_OFFLINE_SECONDS = 48 * 3600  # decay cap: a long absence must not be fatal
NAME_MAX_LEN = 16
