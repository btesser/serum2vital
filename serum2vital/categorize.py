"""Sort converted presets into INSTRUMENT / TYPE / MODIFIER folders.

Serum libraries carry their categories in three places, none of them reliable
on its own: preset names ("LD - Good Vibs", "AU_HM_bass_growl_distorted"),
bank strings (Serum 1 `menu`, Serum 2 tags + description) and the folder the
file came from ("Hardstyle/.../LEADS/").  This module reads all three, in that
order of trust, and falls back to what the converted Vital settings say about
the sound (long attack -> pad, short decay and no sustain -> pluck, ...).

The keyword tables were tuned against the ~8000 preset corpus under
a local Serum library; the prefix codes (BA, LD, PD, SC, ...) are the ones sound
designers actually use, plus a few pack-specific ones (BRM = braam, MB = music
box, HV = hoover).
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping, Sequence

__all__ = ["categorize", "INSTRUMENTS", "safe_part"]

# ---------------------------------------------------------------------------
# Instrument
# ---------------------------------------------------------------------------

# Full words: matched anywhere in a name, bank or folder, case-insensitively.
INSTRUMENT_WORDS: dict[str, str] = {
    # bass
    "BASS": "BASS", "BASSES": "BASS", "BASSLINE": "BASS", "808": "BASS", "808S": "BASS",
    "SUB": "BASS", "SUBS": "BASS", "REESE": "BASS", "GROWL": "BASS", "GROWLS": "BASS",
    "WOBBLE": "BASS", "WOBBLES": "BASS", "WUB": "BASS", "WUBS": "BASS", "YOY": "BASS",
    "DONK": "BASS", "ACID": "BASS", "NEURO": "BASS", "TEAROUT": "BASS",
    # lead
    "LEAD": "LEAD", "LEADS": "LEAD", "SCREECH": "LEAD", "SCREECHES": "LEAD",
    "SCREAM": "LEAD", "SAW": "LEAD", "SOLO": "LEAD",
    # pad
    "PAD": "PAD", "PADS": "PAD", "ATM": "PAD", "ATMOS": "PAD", "ATMOSPHERE": "PAD",
    "DRONE": "PAD", "DRONES": "PAD", "SOUNDSCAPE": "PAD", "SOUNDSCAPES": "PAD",
    "TEXTURE": "PAD", "TEXTURES": "PAD", "AMBIENCE": "PAD",
    # pluck
    "PLUCK": "PLUCK", "PLUCKS": "PLUCK", "PLK": "PLUCK",
    # keys
    "KEY": "KEYS", "KEYS": "KEYS", "KEYBOARD": "KEYS", "PIANO": "KEYS", "PIANOS": "KEYS",
    "ORGAN": "KEYS", "ORGANS": "KEYS", "BELL": "KEYS", "BELLS": "KEYS", "MALLET": "KEYS",
    "MALLETS": "KEYS", "RHODES": "KEYS", "WURLI": "KEYS", "WURLITZER": "KEYS", "CLAV": "KEYS",
    "CLAVINET": "KEYS", "HARPSICHORD": "KEYS", "MUSICBOX": "KEYS", "KALIMBA": "KEYS",
    "MARIMBA": "KEYS", "VIBES": "KEYS", "XYLOPHONE": "KEYS", "GLOCK": "KEYS",
    "GLOCKENSPIEL": "KEYS", "CHIME": "KEYS", "CHIMES": "KEYS", "CELESTA": "KEYS",
    # fx
    "FX": "FX", "SFX": "FX", "EFFECT": "FX", "EFFECTS": "FX", "RISER": "FX", "RISERS": "FX",
    "RISE": "FX", "IMPACT": "FX", "IMPACTS": "FX", "SWEEP": "FX", "SWEEPS": "FX",
    "NOISE": "FX", "DOWNLIFTER": "FX", "DOWNLIFTERS": "FX", "UPLIFTER": "FX",
    "UPLIFTERS": "FX", "BRAAM": "FX", "BRAAMS": "FX", "HIT": "FX", "HITS": "FX",
    "LASER": "FX", "LASERS": "FX", "ZAP": "FX", "ZAPS": "FX", "SIREN": "FX", "SIRENS": "FX",
    "ALARM": "FX", "WHOOSH": "FX", "TRANSITION": "FX", "TRANSITIONS": "FX",
    # drum
    "DRUM": "DRUM", "DRUMS": "DRUM", "DRUMKIT": "DRUM", "KICK": "DRUM", "KICKS": "DRUM",
    "SNARE": "DRUM", "SNARES": "DRUM", "HAT": "DRUM", "HATS": "DRUM", "HIHAT": "DRUM",
    "PERC": "DRUM", "PERCS": "DRUM", "PERCUSSION": "DRUM", "CLAP": "DRUM", "CLAPS": "DRUM",
    "TOM": "DRUM", "TOMS": "DRUM", "CYMBAL": "DRUM", "CRASH": "DRUM", "RIDE": "DRUM",
    # seq
    "SEQ": "SEQ", "SEQUENCE": "SEQ", "SEQUENCES": "SEQ", "ARP": "SEQ", "ARPS": "SEQ",
    "ARPEGGIO": "SEQ", "ARPEGGIATOR": "SEQ", "LOOP": "SEQ", "LOOPS": "SEQ",
    # chord
    "CHORD": "CHORD", "CHORDS": "CHORD", "STAB": "CHORD", "STABS": "CHORD",
    # vocal
    "VOX": "VOCAL", "VOCAL": "VOCAL", "VOCALS": "VOCAL", "VOICE": "VOCAL", "VOICES": "VOCAL",
    "CHOIR": "VOCAL", "CHOIRS": "VOCAL", "FORMANT": "VOCAL", "TALK": "VOCAL", "TALKING": "VOCAL",
    # synth (weak: any other instrument word in the name wins over it)
    "SYN": "SYNTH", "SYNTH": "SYNTH", "SYNTHS": "SYNTH", "SUPERSAW": "SYNTH", "SUPERSAWS": "SYNTH",
    "HYPERSAW": "SYNTH", "HOOVER": "SYNTH", "HOOVERS": "SYNTH",
    # acoustic / orchestral instruments
    "BRASS": "INSTRUMENT", "STRING": "INSTRUMENT", "STRINGS": "INSTRUMENT", "ORCH": "INSTRUMENT",
    "ORCHESTRA": "INSTRUMENT", "ORCHESTRAL": "INSTRUMENT", "FLUTE": "INSTRUMENT",
    "GTR": "INSTRUMENT", "GUITAR": "INSTRUMENT", "GUITARS": "INSTRUMENT", "WIND": "INSTRUMENT",
    "WINDS": "INSTRUMENT", "WOODWIND": "INSTRUMENT", "HORN": "INSTRUMENT", "HORNS": "INSTRUMENT",
    "TRUMPET": "INSTRUMENT", "CELLO": "INSTRUMENT", "VIOLIN": "INSTRUMENT", "HARP": "INSTRUMENT",
    "SITAR": "INSTRUMENT", "INSTRUMENT": "INSTRUMENT", "INSTRUMENTS": "INSTRUMENT",
    "ACOUSTIC": "INSTRUMENT", "ENSEMBLE": "INSTRUMENT",
}

# Short prefix codes: only trusted near the start of a preset name and only
# when written in upper case, because several are ordinary words (OR, RE, HIT).
INSTRUMENT_CODES: dict[str, str] = {
    "BA": "BASS", "BS": "BASS", "RE": "BASS", "AC": "BASS",
    "LD": "LEAD", "SC": "LEAD", "SCR": "LEAD",
    "PD": "PAD", "DRO": "PAD",
    "PL": "PLUCK",
    "KY": "KEYS", "KB": "KEYS", "EP": "KEYS", "PN": "KEYS", "OR": "KEYS", "BL": "KEYS",
    "MB": "KEYS", "MAL": "KEYS",
    "BRM": "FX",
    "DR": "DRUM", "PR": "DRUM", "KIT": "DRUM",
    "SQ": "SEQ",
    "CH": "CHORD",
    "VX": "VOCAL",
    "SY": "SYNTH", "SS": "SYNTH", "HV": "SYNTH",
    "BR": "INSTRUMENT", "STR": "INSTRUMENT", "GT": "INSTRUMENT", "INST": "INSTRUMENT",
}

INSTRUMENTS = ("BASS", "LEAD", "PAD", "PLUCK", "KEYS", "FX", "DRUM", "SEQ", "CHORD",
               "VOCAL", "SYNTH", "INSTRUMENT")

# Bank strings that are performance hints rather than categories ("Use Mod
# Wheel For FX", "Play Chords / Try changing Clip...") must not vote.
BANK_NOISE_WORDS = {"USE", "MOD", "WHEEL", "MACRO", "MACROS", "MW", "TRY", "TURN", "HOLD",
                    "PLAY", "WWW", "HTTP", "HTTPS", "COM", "NET", "DE", "VISIT", "FOR"}

# ---------------------------------------------------------------------------
# Type
# ---------------------------------------------------------------------------

TYPE_WORDS: dict[str, str] = {
    # bass flavours
    "REESE": "REESE", "REESES": "REESE", "WOBBLE": "WOBBLE", "WOBBLES": "WOBBLE", "WUB": "WOBBLE",
    "WUBS": "WOBBLE", "GROWL": "GROWL", "GROWLS": "GROWL", "SUB": "SUB", "SUBS": "SUB",
    "808": "808", "808S": "808", "YOY": "YOY", "YOI": "YOY", "DONK": "DONK", "ACID": "ACID",
    "NEURO": "NEURO", "TEAROUT": "TEAROUT", "MODULATED": "MODULATED", "MDL": "MODULATED",
    "MOOMBAH": "MOOMBAH", "MOOMBAHTON": "MOOMBAH",
    # lead / synth flavours
    "SCREECH": "SCREECH", "SCREECHES": "SCREECH", "SCREAM": "SCREECH", "SCR": "SCREECH",
    "SUPERSAW": "SUPERSAW", "SUPERSAWS": "SUPERSAW", "HYPERSAW": "SUPERSAW",
    "HOOVER": "HOOVER", "HOOVERS": "HOOVER", "HV": "HOOVER", "SAW": "SAW", "SQUARE": "SQUARE",
    "SINE": "SINE", "PWM": "PWM", "FM": "FM", "PLUCK": "PLUCK", "PLUCKS": "PLUCK",
    "PLUCKY": "PLUCK", "SOLO": "SOLO",
    # keys flavours
    "BELL": "BELL", "BELLS": "BELL", "MUSICBOX": "BELL", "MB": "BELL", "CHIME": "BELL",
    "CHIMES": "BELL", "PIANO": "PIANO", "PIANOS": "PIANO", "PN": "PIANO", "EP": "PIANO",
    "RHODES": "PIANO", "WURLI": "PIANO", "ORGAN": "ORGAN", "ORGANS": "ORGAN", "OR": "ORGAN",
    "MALLET": "MALLET", "MALLETS": "MALLET", "MAL": "MALLET", "KALIMBA": "MALLET",
    "MARIMBA": "MALLET", "CLAV": "CLAV",
    # fx flavours
    "RISER": "RISER", "RISERS": "RISER", "RISE": "RISER", "UPLIFTER": "RISER", "UPLIFTERS": "RISER",
    "DOWNLIFTER": "DOWNLIFTER", "DOWNLIFTERS": "DOWNLIFTER", "IMPACT": "IMPACT", "IMPACTS": "IMPACT",
    "HIT": "IMPACT", "HITS": "IMPACT", "SWEEP": "SWEEP", "SWEEPS": "SWEEP", "NOISE": "NOISE",
    "BRAAM": "BRAAM", "BRAAMS": "BRAAM", "BRM": "BRAAM", "LASER": "LASER", "ZAP": "LASER",
    "SIREN": "SIREN", "ALARM": "SIREN", "DRONE": "DRONE", "DRONES": "DRONE", "DRO": "DRONE",
    "ATMOS": "ATMOS", "ATMOSPHERE": "ATMOS", "ATM": "ATMOS", "SOUNDSCAPE": "ATMOS",
    "TEXTURE": "TEXTURE",
    # drum flavours
    "KICK": "KICK", "KICKS": "KICK", "SNARE": "SNARE", "SNARES": "SNARE", "HAT": "HAT",
    "HATS": "HAT", "HIHAT": "HAT", "CLAP": "CLAP", "CLAPS": "CLAP", "PERC": "PERC",
    "PERCS": "PERC", "PERCUSSION": "PERC", "TOM": "TOM", "TOMS": "TOM",
    # seq / chord flavours
    "ARP": "ARP", "ARPS": "ARP", "ARPEGGIO": "ARP", "ARPEGGIATOR": "ARP", "STAB": "STAB",
    "STABS": "STAB", "LOOP": "LOOP", "LOOPS": "LOOP",
    # vocal flavours
    "CHOIR": "CHOIR", "CHOIRS": "CHOIR", "FORMANT": "FORMANT", "TALK": "TALK", "TALKING": "TALK",
    "VOWEL": "FORMANT",
    # instrument flavours
    "BRASS": "BRASS", "HORN": "BRASS", "HORNS": "BRASS", "TRUMPET": "BRASS", "STRING": "STRINGS",
    "STRINGS": "STRINGS", "VIOLIN": "STRINGS", "CELLO": "STRINGS", "STR": "STRINGS",
    "ORCH": "ORCHESTRAL", "ORCHESTRA": "ORCHESTRAL", "ORCHESTRAL": "ORCHESTRAL",
    "FLUTE": "FLUTE", "WIND": "WOODWIND", "WINDS": "WOODWIND", "WOODWIND": "WOODWIND",
    "GUITAR": "GUITAR", "GUITARS": "GUITAR", "GTR": "GUITAR", "ELECTRIC": "ELECTRIC",
    "ACOUSTIC": "ACOUSTIC", "HARP": "HARP", "SITAR": "SITAR",
}
# Type codes that double as ordinary words are, like instrument codes, only
# believed as upper-case tokens near the start of a name.
TYPE_CODES = {"MB", "PN", "EP", "OR", "MAL", "HV", "SCR", "BRM", "DRO", "ATM", "STR", "MDL", "FM"}

GENRE_WORDS: dict[str, str] = {
    "DUBSTEP": "DUBSTEP", "RIDDIM": "DUBSTEP", "BROSTEP": "DUBSTEP", "DEATHSTEP": "DUBSTEP",
    "HARDSTYLE": "HARDSTYLE", "RAWSTYLE": "HARDSTYLE", "RAWPHORIC": "HARDSTYLE",
    "EUPHORIC": "HARDSTYLE", "HARDDANCE": "HARDSTYLE",
    "TRAP": "TRAP", "DRILL": "TRAP",
    "HOUSE": "HOUSE", "ELECTRO": "HOUSE", "GARAGE": "HOUSE", "UKG": "HOUSE",
    "TECHNO": "TECHNO", "TECH": "TECHNO",
    "DNB": "DNB", "DRUMANDBASS": "DNB", "JUNGLE": "DNB", "NEUROFUNK": "DNB", "LIQUID": "DNB",
    "TRANCE": "TRANCE", "PSYTRANCE": "PSYTRANCE", "PSY": "PSYTRANCE", "GOA": "PSYTRANCE",
    "EDM": "EDM", "DANCE": "EDM", "ELECTRONIC": "EDM", "BIGROOM": "EDM", "PROGRESSIVE": "EDM",
    "HIPHOP": "HIPHOP", "RAP": "HIPHOP", "RNB": "HIPHOP", "BOOMBAP": "HIPHOP",
    "FUTUREBASS": "FUTURE_BASS",
    "HARDCORE": "HARDCORE", "UPTEMPO": "HARDCORE", "FRENCHCORE": "HARDCORE", "GABBER": "HARDCORE",
    "HAPPYHARDCORE": "HARDCORE",
    "LOFI": "LOFI", "CHILL": "LOFI", "CHILLOUT": "LOFI",
    "RETRO": "RETRO", "SYNTHWAVE": "RETRO", "80S": "RETRO", "OUTRUN": "RETRO", "VAPORWAVE": "RETRO",
    "DARKSYNTH": "RETRO", "CYBERPUNK": "RETRO", "OLDSCHOOL": "RETRO",
    "CHIPTUNE": "CHIPTUNE", "8BIT": "CHIPTUNE", "ARCADE": "CHIPTUNE", "BARCADE": "CHIPTUNE",
    "AMBIENT": "AMBIENT", "AMBIENCE": "AMBIENT",
    "CINEMATIC": "CINEMATIC", "TRAILER": "CINEMATIC", "SCORE": "CINEMATIC",
    "POP": "POP", "FUNK": "FUNK", "DISCO": "DISCO", "REGGAETON": "REGGAETON", "DANCEHALL": "REGGAETON",
    "GLITCHHOP": "GLITCH_HOP", "COMPLEXTRO": "COMPLEXTRO", "MOOMBAHTON": "MOOMBAH",
    "PHONK": "PHONK",
}
# Two-token genre names that tokenising splits apart.
GENRE_PAIRS: dict[tuple[str, str], str] = {
    ("HIP", "HOP"): "HIPHOP", ("FUTURE", "BASS"): "FUTURE_BASS", ("DRUM", "AND"): "DNB",
    ("DRUM", "N"): "DNB", ("D", "B"): "DNB", ("D", "N"): "DNB", ("BASS", "HOUSE"): "HOUSE",
    ("DEEP", "HOUSE"): "HOUSE", ("TECH", "HOUSE"): "HOUSE", ("HARD", "DANCE"): "HARDSTYLE",
    ("HARD", "HOUSE"): "HARDSTYLE", ("HARD", "TRANCE"): "TRANCE", ("HARD", "TECHNO"): "TECHNO",
    ("HYPER", "TECHNO"): "TECHNO", ("GLITCH", "HOP"): "GLITCH_HOP", ("LO", "FI"): "LOFI",
    ("HAPPY", "HARDCORE"): "HARDCORE", ("MELODIC", "DUBSTEP"): "DUBSTEP",
    ("BIG", "ROOM"): "EDM", ("MELODIC", "BASS"): "FUTURE_BASS", ("COLOUR", "BASS"): "FUTURE_BASS",
    ("COLOR", "BASS"): "FUTURE_BASS", ("SYNTH", "WAVE"): "RETRO", ("8", "BIT"): "CHIPTUNE",
    ("HYBRID", "TRAP"): "TRAP",
}

# ---------------------------------------------------------------------------
# Modifier
# ---------------------------------------------------------------------------

MODIFIER_WORDS: dict[str, str] = {
    "AGGRESSIVE": "AGGRESSIVE", "AGGRO": "AGGRESSIVE", "HARSH": "AGGRESSIVE", "BRUTAL": "AGGRESSIVE",
    "ANGRY": "AGGRESSIVE", "VIOLENT": "AGGRESSIVE", "INSANE": "AGGRESSIVE", "SAVAGE": "AGGRESSIVE",
    "HARD": "HARD", "PUNCHY": "HARD", "PUNCH": "HARD", "HEAVY": "HEAVY", "MASSIVE": "HEAVY",
    "DIRTY": "DIRTY", "FILTHY": "DIRTY", "GRITTY": "DIRTY", "CRUNCHY": "DIRTY", "RAW": "DIRTY",
    "NASTY": "DIRTY", "GNARLY": "DIRTY",
    "DISTORTED": "DISTORTED", "DIST": "DISTORTED", "DISTORTION": "DISTORTED", "OVERDRIVE": "DISTORTED",
    "OVERDRIVEN": "DISTORTED", "SATURATED": "DISTORTED", "FUZZ": "DISTORTED", "METAL": "METALLIC",
    "METALLIC": "METALLIC",
    "SOFT": "SOFT", "GENTLE": "SOFT", "MELLOW": "SOFT", "DREAMY": "SOFT", "LIGHT": "SOFT",
    "DELICATE": "SOFT", "CLEAN": "CLEAN", "PURE": "CLEAN", "SIMPLE": "CLEAN", "BASIC": "CLEAN",
    "SMOOTH": "SMOOTH", "SILKY": "SMOOTH", "LIQUID": "SMOOTH",
    "DARK": "DARK", "DEEP": "DARK", "EVIL": "DARK", "SCARY": "DARK", "CREEPY": "DARK",
    "SPOOKY": "DARK", "HORROR": "DARK", "GLOOMY": "DARK", "OMINOUS": "DARK", "MUDDY": "DARK",
    "BRIGHT": "BRIGHT", "AIRY": "BRIGHT", "GLASSY": "BRIGHT", "SHINY": "BRIGHT", "SPARKLE": "BRIGHT",
    "SPARKLY": "BRIGHT", "HAPPY": "BRIGHT", "UPLIFTING": "BRIGHT", "GLOWING": "BRIGHT",
    "WIDE": "WIDE", "STEREO": "WIDE", "LUSH": "WIDE", "DETUNED": "WIDE", "HUGE": "HUGE",
    "BIG": "HUGE", "EPIC": "HUGE", "GIANT": "HUGE", "MONSTER": "HUGE", "FAT": "FAT", "PHAT": "FAT",
    "THICK": "FAT", "THIN": "THIN", "HOLLOW": "THIN", "TINY": "THIN",
    "ANALOG": "ANALOG", "ANALOGUE": "ANALOG", "DIGITAL": "DIGITAL", "RETRO": "RETRO",
    "VINTAGE": "VINTAGE", "CLASSIC": "VINTAGE", "OLD": "VINTAGE", "WARM": "WARM", "COLD": "COLD",
    "ICY": "COLD", "ICE": "COLD", "FROZEN": "COLD", "GLITCH": "GLITCH", "GLITCHY": "GLITCH",
    "BROKEN": "GLITCH", "EVOLVING": "EVOLVING", "MORPH": "EVOLVING", "MORPHING": "EVOLVING",
    "MOVING": "EVOLVING", "MOTION": "EVOLVING", "RHYTHMIC": "RHYTHMIC", "RHYTHM": "RHYTHMIC",
    "GATED": "GATED", "GATE": "GATED", "SIDECHAIN": "SIDECHAIN", "SIDECHAINED": "SIDECHAIN",
    "PUMPING": "SIDECHAIN", "MONO": "MONO", "WET": "WET", "DRY": "DRY", "SPACEY": "WET",
    "ECHO": "WET", "REVERBY": "WET",
}

FOLDER_SAFE = re.compile(r"[^A-Z0-9_]")


def safe_part(word: str, default: str = "GENERAL") -> str:
    """Make a folder-name-safe UPPERCASE token (letters, digits, underscore)."""
    cleaned = FOLDER_SAFE.sub("_", word.upper()).strip("_")
    return cleaned or default


def _tokens(text: str) -> list[str]:
    """Split on anything that is not a letter or digit, keeping original case."""
    if not text:
        return []
    return [t for t in re.split(r"[^A-Za-z0-9]+", text) if t]


def _folder_tokens(path: str, depth: int = 4) -> list[list[str]]:
    """Tokens of the last `depth` folders, deepest first."""
    parts = re.split(r"[\\/]+", path.replace("\\", "/"))
    folders = [p for p in parts[:-1] if p and p not in (".", "..")]
    return [_tokens(f) for f in reversed(folders[-depth:])]


def _squash(tokens: Sequence[str]) -> list[str]:
    """Upper-case tokens plus the joined form of adjacent pairs ("Hip", "Hop")."""
    upper = [t.upper() for t in tokens]
    joined = [a + b for a, b in zip(upper, upper[1:])]
    return upper + joined


def _strip_genre_pairs(tokens: Sequence[str]) -> list[str]:
    """Drop tokens that only spell a genre ("Bass House", "Future Bass", "Drum and Bass")."""
    upper = [t.upper() for t in tokens]
    drop: set[int] = set()
    for i, pair in enumerate(zip(upper, upper[1:])):
        if pair in GENRE_PAIRS:
            drop.update((i, i + 1))
            if pair in (("DRUM", "AND"), ("DRUM", "N")) and i + 2 < len(upper):
                drop.add(i + 2)  # the "Bass" in "Drum and Bass"
    return [t for i, t in enumerate(tokens) if i not in drop]


def _all_words(tokens: Sequence[str], table: Mapping[str, str], codes: Iterable[str] = (),
               code_window: int = 4) -> list[str]:
    codes = set(codes)
    found = []
    for index, raw in enumerate(tokens):
        upper = raw.upper()
        if upper in table and not (upper in codes and (index >= code_window or raw != upper)):
            found.append(table[upper])
    return found


def _instrument_from(tokens: Sequence[str], codes: bool) -> str | None:
    """Pick an instrument from tokens; SYNTH only wins when nothing else appears."""
    table = dict(INSTRUMENT_WORDS)
    code_set: set[str] = set()
    if codes:
        table.update(INSTRUMENT_CODES)
        code_set = set(INSTRUMENT_CODES)
    hits = _all_words(_strip_genre_pairs(tokens), table, code_set)
    for hit in hits:
        if hit != "SYNTH":
            return hit
    return hits[0] if hits else None


def _bank_is_noise(tokens: Sequence[str]) -> bool:
    upper = {t.upper() for t in tokens}
    return bool(upper & BANK_NOISE_WORDS)


def _genre(*token_lists: Sequence[str]) -> str | None:
    for tokens in token_lists:
        upper = [t.upper() for t in tokens]
        for a, b in zip(upper, upper[1:]):
            if (a, b) in GENRE_PAIRS:
                return GENRE_PAIRS[(a, b)]
        for t in _squash(tokens):
            if t in GENRE_WORDS:
                return GENRE_WORDS[t]
    return None


def _setting(settings: Mapping[str, float], key: str, default: float = 0.0) -> float:
    value = settings.get(key)
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _instrument_from_settings(settings: Mapping[str, float]) -> str | None:
    """Rough guesses from the converted Vital parameters (last resort)."""
    if not settings:
        return None
    attack = _setting(settings, "env_1_attack")          # seconds ** 0.25
    decay = _setting(settings, "env_1_decay", 1.0)
    sustain = _setting(settings, "env_1_sustain", 1.0)
    release = _setting(settings, "env_1_release")
    transpose = _setting(settings, "osc_1_transpose")
    osc_on = _setting(settings, "osc_1_on", 1.0) or _setting(settings, "osc_2_on") \
        or _setting(settings, "osc_3_on")
    sample_on = _setting(settings, "sample_on")

    if sample_on and not osc_on:
        return "DRUM"
    if attack >= 0.84:                                    # >= ~0.5 s attack
        return "PAD"
    if sustain <= 0.05 and decay <= 1.1:                  # decay <= ~1.5 s, no sustain
        return "DRUM" if release <= 0.5 and decay <= 0.75 and transpose <= -12 else "PLUCK"
    if transpose <= -12:
        return "BASS"
    return None


def _modifier_from_settings(settings: Mapping[str, float], notes: Sequence[str]) -> str:
    hyper = any("hyper" in note.lower() for note in notes)
    if not settings and not hyper:
        return "CLEAN"
    warp = int(_setting(settings, "osc_1_distortion_type"))
    if (_setting(settings, "distortion_on") and _setting(settings, "distortion_drive") >= 12.0) \
            or 7 <= warp <= 12:
        return "AGGRESSIVE"
    voices = max(_setting(settings, "osc_1_unison_voices", 1.0),
                 _setting(settings, "osc_2_unison_voices", 1.0))
    # Serum's Hyper is a widening chorus, so it counts as WIDE rather than AGGRESSIVE.
    if voices >= 5 or _setting(settings, "chorus_on") or hyper:
        return "WIDE"
    if _setting(settings, "filter_1_on") and _setting(settings, "filter_1_cutoff", 128.0) <= 55.0:
        return "DARK"
    if _setting(settings, "reverb_on") and _setting(settings, "delay_on"):
        return "WET"
    return "CLEAN"


def categorize(name: str, bank: str = "", path: str = "", tags: Sequence[str] | None = None,
               settings: Mapping[str, float] | None = None, *,
               notes: Sequence[str] = ()) -> tuple[str, str, str]:
    """Classify a preset as (INSTRUMENT, TYPE, MODIFIER), all folder-safe upper case.

    `bank` is the Serum 1 menu string or the Serum 2 description, `tags` the
    Serum 2 tag list, `path` the source file, `settings` the converted Vital
    parameter dict and `notes` the conversion notes (used to spot Serum's
    Hyper effect, which has no parameter of its own in Vital).
    """
    tags = list(tags or [])
    settings = settings or {}
    name_tokens = _tokens(name)
    bank_tokens = _tokens(bank)
    tag_tokens = [t for tag in tags for t in _tokens(tag)]
    folders = _folder_tokens(path)
    parent = folders[0] if folders else []

    # --- instrument -------------------------------------------------------
    instrument = _instrument_from(name_tokens, codes=True)
    if instrument is None and not _bank_is_noise(bank_tokens):
        instrument = _instrument_from(bank_tokens, codes=False)
    if instrument is None and "Arp" in tags:
        instrument = "SEQ"
    if instrument is None:
        for folder in folders:
            instrument = _instrument_from(folder, codes=False)
            if instrument:
                break
    if instrument is None:
        instrument = _instrument_from_settings(settings)
    if instrument is None:
        instrument = "SYNTH"

    # --- type -------------------------------------------------------------
    type_ = None
    candidates = [
        (name_tokens, TYPE_CODES),
        (bank_tokens if not _bank_is_noise(bank_tokens) else [], TYPE_CODES),
        (parent, ()),
    ]
    for tokens, codes in candidates:
        for hit in _all_words(tokens, TYPE_WORDS, codes):
            if hit != instrument:
                type_ = hit
                break
        if type_:
            break
    if type_ is None:
        type_ = _genre(name_tokens, bank_tokens, tag_tokens, *folders)
    if type_ is None:
        type_ = "GENERAL"

    # --- modifier ---------------------------------------------------------
    modifier = None
    for tokens in (name_tokens, bank_tokens if not _bank_is_noise(bank_tokens) else [], parent):
        for hit in _all_words(tokens, MODIFIER_WORDS):
            if hit != type_:
                modifier = hit
                break
        if modifier:
            break
    if modifier is None:
        modifier = _modifier_from_settings(settings, notes)

    return safe_part(instrument, "SYNTH"), safe_part(type_), safe_part(modifier, "CLEAN")
