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
    'cat':          {'title': '🐱 Кот',          'img': 'pet.png',              'faces': True},
    'dog':          {'title': '🐶 Щенок',        'img': 'pet_dog.png',          'faces': False},
    'bunny':        {'title': '🐰 Кролик',       'img': 'pet_bunny.png',        'faces': False},
    'hamster':      {'title': '🐹 Хомяк',        'img': 'pet_hamster.png',      'faces': False},
    'fox':          {'title': '🦊 Лисёнок',      'img': 'pet_fox.png',          'faces': False},
    'duck':         {'title': '🦆 Утёнок',       'img': 'pet_duck.png',         'faces': False},
    'panda':        {'title': '🐼 Панда',        'img': 'pet_panda.png',        'faces': False},
    'snow_leopard': {'title': '🐆 Снежный барс', 'img': 'pet_snow_leopard.png', 'faces': False},
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
