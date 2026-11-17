"""Species registry: the foundation for pet skins.

A pet is not necessarily a cat any more: every unlockable look is a
"species" here. This module is the single source of truth used by the
state model (validation), the engine (grants and switching) and the
Mini App UI (rendering). Adding a new species = one dict entry plus one
PNG in webapp/assets/ (name in 'img'). Nothing else needs to change.

'faces' marks species that have face_N.png emotion overlays in
webapp/assets/; species without overlays just don't show the emotion
frame in the UI.
"""

SPECIES = {
    'cat':          {'title': '🐱 Кот',          'img': 'pet.png',              'faces': True,
                     'sleep': 'pet_cat_sleep.png'},
    'dog':          {'title': '🐶 Щенок',        'img': 'pet_dog.png',          'faces': False,
                     'sleep': 'pet_dog_sleep.png', 'where': 'chest'},
    'bunny':        {'title': '🐰 Кролик',       'img': 'pet_bunny.png',        'faces': False,
                     'sleep': 'pet_bunny_sleep.png', 'where': 'chest'},
    'hamster':      {'title': '🐹 Хомяк',        'img': 'pet_hamster.png',      'faces': False,
                     'sleep': 'pet_hamster_sleep.png', 'where': 'chest'},
    'fox':          {'title': '🦊 Лисёнок',      'img': 'pet_fox.png',          'faces': False,
                     'sleep': 'pet_fox_sleep.png', 'where': 'chest'},
    'duck':         {'title': '🦆 Утёнок',       'img': 'pet_duck.png',         'faces': False,
                     'sleep': 'pet_duck_sleep.png', 'where': 'chest'},
    'panda':        {'title': '🐼 Панда',        'img': 'pet_panda.png',        'faces': False,
                     'sleep': 'pet_panda_sleep.png', 'where': 'chest'},
    'snow_leopard': {'title': '🐆 Снежный барс', 'img': 'pet_snow_leopard.png', 'faces': False,
                     'sleep': 'pet_snow_leopard_sleep.png', 'where': 'promo'},
}

DEFAULT_SPECIES = 'cat'


def is_species(species_id: str) -> bool:
    return species_id in SPECIES


def species_or_default(species_id: str) -> str:
    """Validate an arbitrary (storage/client) species id against the registry."""
    return species_id if species_id in SPECIES else DEFAULT_SPECIES


def species_title(species_id: str) -> str:
    return SPECIES[species_or_default(species_id)]['title']


def species_img(species_id: str) -> str:
    return SPECIES[species_or_default(species_id)]['img']


def has_faces(species_id: str) -> bool:
    return bool(SPECIES[species_or_default(species_id)]['faces'])
