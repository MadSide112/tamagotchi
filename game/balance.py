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

# --- auto sleep: pet sleeps 23:00–07:00 by the user's local time ---
NIGHT_START_HOUR = 23.0
NIGHT_END_HOUR = 7.0

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
DAILY_REWARDS = [                 # цикл 7 дней: награда за первый вход в сутки
    {'coins': 10,      'label': '+10 🪙'},
    {'coins': 20,      'label': '+20 🪙'},
    {'item': 'cake',   'n': 1, 'label': '🍰 Торт'},
    {'coins': 70,      'label': '+70 🪙'},
    {'case': 'golden', 'label': '🧰 Золотой сундук'},
    {'coins': 100,     'label': '+100 🪙'},
    {'case': 'golden', 'label': '🧰 Золотой сундук'},
]
REF_BONUS = 50                    # both referrer and invitee

SHOP = {
    'apple':   {'price': 5,  'title': '🍎 Яблоко',    'kind': 'food'},
    'fish':    {'price': 10, 'title': '🐟 Рыбка',     'kind': 'food'},
    'cake':    {'price': 15, 'title': '🍰 Торт',      'kind': 'food'},
    'med':     {'price': 20, 'title': '💊 Лекарство', 'kind': 'med'},
    'bow':     {'price': 30, 'title': '🎀 Бантик',    'kind': 'accessory'},
    'scarf':   {'price': 35, 'title': '🧣 Шарф',      'kind': 'accessory'},
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
NAME_MAX_LEN = 15

# ======================= PROGRESSION 2.0 =======================

# --- XP и уровни (ось прогрессии, независимая от стадии эволюции) ---
LEVEL_XP_BASE = 60   # XP для перехода с 1 на 2 уровень
LEVEL_XP_STEP = 26   # need(l) = LEVEL_XP_BASE + LEVEL_XP_STEP*(l-1)
MAX_LEVEL = 30
# XP за успешные действия по уходу (меньше, чем в мини-играх — забота фоновая)
XP_GRANTS = {'feed': 3, 'clean': 3, 'play': 4, 'pet': 2, 'heal': 6}
QUEST_CLAIM_XP = 15          # XP за сдачу всех дневных квестов
BOOST_XP_MULT = 2.0          # «Эликсир роста» (промокод)
GEN_XP_BONUS = 0.10          # +10% XP за каждое поколение (Зал Славы)

# --- скрытые статы и классы взрослого ---
HIDDEN_CAP = 100.0
CLASS_MIN_STAT = 20.0        # доминирующий стат нужен >= порога, иначе класс не присвоен
CHARISMA_PER_HOUR = 0.6      # капает, пока чистота >= CHARISMA_HYGIENE_MIN
CHARISMA_HYGIENE_MIN = 90.0
WEAR_CHARISMA = 2.0          # за надевание аксессуара
CLASS_XP_MULT_MAGE = 1.2     # маг: +20% XP от мини-игр и квестов
CLASS_COIN_MULT_WARRIOR = 1.15  # воин: +15% монет в мини-играх
HUNGER_DECAY_NOBLE_MULT = 0.75  # аристократ: голод падает на 25% медленнее
CLASSES = {
    'warrior': {'title': 'Воин ⚔️', 'stat': 'p', 'desc': '+15% монет в мини-играх'},
    'mage': {'title': 'Маг 🔮', 'stat': 'iq', 'desc': '+20% XP в мини-играх и квестах'},
    'noble': {'title': 'Аристократ 👑', 'stat': 'ch', 'desc': '−25% голод'},
}

# --- комната: улучшения (магазин kind='room', цены за уровень) ---
ROOM = {
    'bowl': {'title': '🥣 Миска', 'prices': [60, 140, 280],
             'desc': 'кормление даёт +4 сытости за уровень'},
    'bed': {'title': '🛏 Кровать', 'prices': [80, 180, 340],
            'desc': 'сон восстанавливает +15% энергии в час за уровень'},
    'zone': {'title': '🎾 Игровая зона', 'prices': [90, 200, 360],
             'desc': '+25% настроения за игру и +5% очков мини-игр за уровень'},
    'tree': {'title': '🌳 Денежное дерево', 'prices': [250, 500],
             'desc': '+3🪙 в час за уровень, собери тапом (копит 12 ч)'},
}
TREE_COINS_PER_HOUR = 3.0    # за уровень дерева
TREE_CAP_HOURS = 12.0        # дерево копит не дольше 12 ч
BOWL_SATIETY_PER_LEVEL = 4.0
BED_REGEN_PER_LEVEL = 0.15
ZONE_PLAY_MOOD_PER_LEVEL = 0.25
ZONE_SCORE_PER_LEVEL = 0.05

# --- мини-игры ---
MG_ENERGY_COST = 15.0        # списывается при зачтённом финише
MG_MIN_SECONDS = 15          # короче — результат не засчитан (анти-чит)
MG_MAX_SECONDS = 300
MG_DAILY_COIN_CAP = 250      # мягкий кап монет из мини-игр в сутки (UTC)
MG_GAMES_DAILY_CAP = 40
MG_GEMS_DAILY_CAP = 5
MG_SCORE_CAPS = {'catch': 120, 'fish': 5, 'simon': 12}
MG_GAMES = {
    'catch': {'title': '🧺 Ловец вкусняшек', 'stat': 'p',
              'desc': 'Веди пальцем — лови вкусняшки, уворачивайся от бомб'},
    'fish': {'title': '🎣 Тайминг-рыбалка', 'stat': 'p',
             'desc': 'Тапни, когда ползунок в зелёной зоне — 5 забросов'},
    'simon': {'title': '⚗️ Алхимия памяти', 'stat': 'iq',
              'desc': 'Повторяй последовательность вспышек на колбах'},
}
MG_GEM_ROUND = 6             # симон: кристаллы начинают капать с этого раунда

# --- дневные квесты (3 случайных из пула, детерминированно на день) ---
QUEST_POOL = (
    {'id': 'feed3', 'act': 'feed', 'need': 3, 'reward': 15, 'title': 'Покормить 3 раза'},
    {'id': 'clean2', 'act': 'clean', 'need': 2, 'reward': 15, 'title': 'Помыть 2 раза'},
    {'id': 'pet5', 'act': 'pet', 'need': 5, 'reward': 12, 'title': 'Погладить 5 раз'},
    {'id': 'case1', 'act': 'open_case', 'need': 1, 'reward': 20, 'title': 'Открыть сундук'},
    {'id': 'buy1', 'act': 'buy', 'need': 1, 'reward': 15, 'title': 'Купить любой товар'},
    {'id': 'mg2', 'act': 'game_end', 'need': 2, 'reward': 20, 'title': 'Сыграть 2 мини-игры'},
    {'id': 'sleep1', 'act': 'sleep', 'need': 1, 'reward': 10, 'title': 'Уложить спать'},
    {'id': 'heal1', 'act': 'heal', 'need': 1, 'reward': 15, 'title': 'Вылечить питомца'},
)
QUESTS_PER_DAY = 3
QUEST_ALL_BONUS = 25         # бонус за все три квеста дня

# --- осколки яиц редких питомцев (мифический сундук) ---
FRAG_NEED = {'fox': 5, 'panda': 8, 'snow_leopard': 12}
FRAG_DUPE_COINS = 150        # осколки на уже собранного питомца

# --- дружба: визиты в комнату друга ---
FRIEND_POINTS_PER_VISIT = 1
FRIEND_VISIT_COOLDOWN_HOURS = 20
FRIEND_ACC = {'ring': {'need': 10, 'title': '💍 Кольцо дружбы'}}
