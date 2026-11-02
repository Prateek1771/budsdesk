"""Nothing / CMF audio models: identity + capabilities.

All of them speak the same 0x55 RFCOMM protocol; they differ in what they support.
Facts come from community reverse-engineering of the Nothing X app (ear-web's device
config + per-model pages, EarA's SKU table, something-x). Only B172 (CMF Buds Pro 2) is
verified on hardware here; every other entry is community data (`verified: False`).

Gesture keys are "device-button-type":
  device 2/3 = left/right bud, 4 = case (Smart Dial / case button), 6 = headphones/neckband
  button 1 = normal, 9 = during-call, 10 = headphone button, 5 = headphone slider
  type 1 single, 2 double, 3 triple, 7 hold, 9 double-hold, 10 rotate, 11 pinch both buds
"""
import re

# ANC capability bitmask (Nothing X "ancLevel")
_TRANS, _STRENGTH, _MID, _ADAPTIVE = 0x10, 0x04, 0x02, 0x08

LISTENING = ["Balanced", "Rock", "Electronic", "Pop", "Enhance Vocals", "Classical", "Custom"]
PRESETS = ["Balanced", "More Bass", "More Treble", "Voice"]

GENERIC_ACTIONS = [2, 8, 9, 10, 11, 18, 19, 1]  # safe media/noise actions for unknown slots


def _bud(table):
    """same action list on both buds: {type: [actions]} -> gesture dict"""
    return {f"{d}-1-{t}": a for d in (2, 3) for t, a in table.items()}


_KNOB = {  # case Smart Dial / smart knob (B172 family, B189)
    "4-1-1": [2, 9, 8, 11, 17, 1], "4-1-2": [2, 9, 8, 11, 17, 1], "4-9-2": [3, 25, 1],
    "4-1-3": [2, 9, 8, 11, 17, 1], "4-9-3": [26, 1], "4-1-7": [11, 17, 1], "4-1-10": [23, 1],
}

_G = {
    "one": _bud({3: [8, 9, 11, 1], 7: [10, 1]}),
    "stick": _bud({2: [8, 9, 11], 3: [8, 9, 11], 7: [18, 19, 11, 10], 9: [1, 18, 19, 11, 10]}),
    "two": _bud({2: [8, 9, 11], 3: [8, 9, 11], 7: [10, 18, 19, 11], 9: [10, 18, 19, 11, 1]}),
    "buds_pro": _bud({2: [2, 8, 9, 11], 3: [8, 9, 11], 7: [10, 11], 9: [18, 19, 11, 1]}),
    "buds": _bud({2: [2, 8, 9, 11, 1], 3: [8, 9, 11, 1], 7: [10, 11, 1], 9: [18, 19, 11, 1]}),
    "open": _bud({2: [8, 9, 11], 3: [8, 9, 11], 7: [18, 19, 11], 9: [18, 19, 11, 1]}),
    "ear3": {**_bud({2: [8, 9, 11], 3: [8, 9, 11, 1], 7: [10, 18, 19, 11, 29, 1], 9: [10, 18, 19, 11, 1]}), "4-1-7": [33, 11, 1]},
    "ear3a": {**_bud({2: [9, 8, 11, 31], 3: [9, 8, 11, 31, 1], 7: [10, 18, 19, 37, 11, 31, 29, 1], 9: [10, 18, 19, 37, 11, 31, 1]}),
              "2-1-11": [37, 1], "3-1-11": [37, 1]},
    "clip": {**_bud({2: [8, 9, 11, 1], 3: [8, 9, 11, 1], 7: [18, 19, 11, 1], 9: [18, 19, 11, 1]}), **_KNOB},
    "neckband": {"6-1-2": [8, 9, 11], "6-1-3": [8, 9, 11], "6-1-7": [10]},
    "hp1": {"6-10-1": [32, 11, 31, 10, 27, 29, 34, 1], "6-10-7": [32, 11, 31, 10, 27, 33, 29, 34, 1], "6-1-7": [10, 1]},
    "hp_a": {"6-10-1": [32, 11, 31, 10, 24, 29, 34, 1], "6-10-7": [32, 11, 31, 10, 33, 29, 34, 1], "6-1-7": [10, 1]},
    "hp1pro": {"6-10-1": [11, 31, 10, 24, 29, 1], "6-10-7": [11, 10, 29, 31, 1], "6-1-7": [10, 1]},
    "cmf_hp": {"6-10-1": [31, 11, 10, 27, 29, 1], "6-10-7": [31, 11, 10, 27, 33, 29, 1], "6-5-1": [35, 36], "6-1-7": [10]},
}
_G["pro2"] = {**_G["buds"], **_KNOB}


def _m(name, anc=0x3F, eq="presets", bass=False, bass3=False, gestures=None, unit="buds", in_ear=True,
       low_lag=True, dial=False, verified=False):
    custom = eq == "listening"  # 3-band custom EQ (F041) is confirmed for the listening-mode family
    return {
        "name": name, "verified": verified, "gestures": gestures or {},
        "features": {
            "anc": anc > 0, "transparency": bool(anc & _TRANS),
            "anc_levels": (["high", "mid", "low"] if anc & _MID else ["high", "low"]) + (["adaptive"] if anc & _ADAPTIVE else [])
            if anc & _STRENGTH else (["high"] if anc else []),
            "eq": eq, "eq_names": (LISTENING if eq == "listening" else PRESETS) if eq else [],
            "custom_eq": custom, "custom_index": 6 if custom else -1,
            "bass": bass, "bass_levels": 2 if bass3 else 5, "bass_wire": [0, 5, 10] if bass3 else None,
            "dial": dial, "unit": unit, "in_ear": in_ear and unit == "buds", "low_lag": low_lag,
            "find": True, "gestures": True,
        },
    }


MODELS = {
    "B181": _m("Nothing Ear (1)", anc=53, gestures=_G["one"]),
    "B157": _m("Nothing Ear (stick)", anc=0, gestures=_G["stick"]),
    "B155": _m("Nothing Ear (2)", gestures=_G["two"]),
    "B171": _m("Nothing Ear", bass=True, gestures=_G["two"]),
    "B162": _m("Nothing Ear (a)", bass=True, gestures=_G["two"]),
    "B183": _m("Nothing Ear (a)", bass=True, gestures=_G["two"]),
    "B173": _m("Nothing Ear (3)", bass=True, gestures=_G["ear3"]),
    "B190": _m("Nothing Ear (3a)", gestures=_G["ear3a"]),
    "B174": _m("Nothing Ear (open)", anc=0, gestures=_G["open"], in_ear=False),
    "B163": _m("CMF Buds Pro", anc=55, gestures=_G["buds_pro"]),
    "B168": _m("CMF Buds", anc=49, eq="listening", bass=True, gestures=_G["buds"]),
    "B172": _m("CMF Buds Pro 2", eq="listening", bass=True, gestures=_G["pro2"], dial=True, verified=True),
    "B187": _m("CMF Buds Pro 2", eq="listening", bass=True, gestures=_G["pro2"], dial=True),
    "B195": _m("CMF Buds Pro 2", eq="listening", bass=True, bass3=True, gestures=_G["pro2"], dial=True),
    "B179": _m("CMF Buds 2", eq="listening", bass=True),
    "B197": _m("CMF Buds 2", eq="listening", bass=True, bass3=True),
    "B184": _m("CMF Buds 2 Plus", eq="listening", bass=True),
    "B185": _m("CMF Buds 2a", anc=49, eq="listening", bass=True),
    "B189": _m("CMF Clip Pro", anc=0, eq="listening", bass=True, bass3=True, gestures=_G["clip"], dial=True, in_ear=False),
    "B164": _m("CMF Neckband Pro", bass=True, gestures=_G["neckband"], unit="stereo"),
    "B170": _m("Nothing Headphone (1)", bass=True, gestures=_G["hp1"], unit="stereo"),
    "B192": _m("Nothing Headphone (1) Pro", gestures=_G["hp1pro"], unit="stereo"),
    "B186": _m("Nothing Headphone (a)", bass=True, bass3=True, gestures=_G["hp_a"], unit="stereo"),
    "B198": _m("Nothing Headphone (a)", bass=True, bass3=True, gestures=_G["hp_a"], unit="stereo"),
    "B175": _m("CMF Headphone Pro", eq="listening", gestures=_G["cmf_hp"], unit="stereo"),
}
GENERIC = _m("Nothing device")
GENERIC["features"]["anc_levels"] = ["high", "mid", "low", "adaptive"]

# serial number SKU (2 digits) -> model base
_SKU = {
    "B181": "01 02 03 04 06 07 08 10", "B157": "14 15 16", "B155": "17 18 19 27 28 29",
    "B163": "30 31 32 33 34 35", "B164": "48 49 50 51 52 53", "B168": "54 55 56 57 58 59",
    "B171": "61 62 69 70 71 74 75", "B162": "63 64 65 66 67 68 72 73", "B172": "76 77 78 79 80 81 82 83",
}
SKU_TO_BASE = {sku: base for base, s in _SKU.items() for sku in s.split()}

# Bluetooth-name hints, most specific first
NAME_HINTS = [
    ("headphone (1) pro", "B192"), ("headphone (1)", "B170"), ("headphone (a)", "B186"), ("headphone pro", "B175"),
    ("ear (3a)", "B190"), ("ear (3)", "B173"), ("ear (open)", "B174"), ("ear (stick)", "B157"), ("ear (a)", "B162"),
    ("ear (2)", "B155"), ("ear (1)", "B181"), ("clip pro", "B189"), ("buds pro 2", "B172"), ("buds 2a", "B185"),
    ("buds 2 plus", "B184"), ("buds 2", "B179"), ("buds pro", "B163"), ("neckband", "B164"), ("cmf buds", "B168"),
    ("nothing ear", "B171"),
]


def base_from_serial(serial):
    """Serial -> base. 'SH'/'13' serials carry the SKU at [4:6]; 'MA' serials encode the year."""
    if not serial:
        return None
    head = serial[:2]
    if head in ("SH", "13"):
        return SKU_TO_BASE.get(serial[4:6])
    if head == "MA":
        return {"22": "B157", "23": "B157", "24": "B174"}.get(serial[6:8])
    return "B174" if serial.startswith("11200005") else None


def base_from_name(name):
    low = (name or "").lower()
    return next((b for needle, b in NAME_HINTS if needle in low), None)


def resolve(serial=None, name=None):
    """Best guess for a device: serial first (precise), then Bluetooth name, else GENERIC."""
    base = base_from_serial(serial) or base_from_name(name)
    m = MODELS.get(base, GENERIC)
    return {"base": base if base in MODELS else "generic", **m}


NOTHING_NAME = re.compile(r"nothing|cmf|\bear ?\(|headphone ?\(", re.I)


if __name__ == "__main__":
    # the real CMF Buds Pro 2 here: its serial isn't in the community SKU table, so the name decides
    assert base_from_serial("1351000000000000") is None and resolve("1351000000000000", "CMF Buds Pro 2")["base"] == "B172"
    assert resolve("SH10762543006451")["base"] == "B172"  # SKU 76
    assert resolve(None, "CMF Buds Pro 2")["base"] == "B172"
    assert resolve(None, "Nothing Ear (3a)")["base"] == "B190" and resolve(None, "Nothing Ear (3)")["base"] == "B173"
    assert resolve(None, "Nothing Headphone (1) Pro")["base"] == "B192" and resolve(None, "Nothing Headphone (1)")["base"] == "B170"
    assert resolve(None, "CMF Buds 2a")["base"] == "B185" and resolve(None, "CMF Buds 2")["base"] == "B179"
    assert resolve(None, "Some speaker")["base"] == "generic"
    assert MODELS["B172"]["features"]["anc_levels"] == ["high", "mid", "low", "adaptive"]
    assert MODELS["B181"]["features"]["anc_levels"] == ["high", "low"] and not MODELS["B157"]["features"]["anc"]
    assert MODELS["B168"]["features"]["anc_levels"] == ["high"] and MODELS["B168"]["features"]["transparency"]
    assert MODELS["B170"]["features"]["unit"] == "stereo" and not MODELS["B170"]["features"]["in_ear"]
    assert MODELS["B172"]["gestures"]["4-1-10"] == [23, 1] and MODELS["B172"]["features"]["dial"]
    keys = set(GENERIC["features"])
    for base, m in MODELS.items():
        assert set(m["features"]) == keys, base
        assert all(re.fullmatch(r"\d-\d+-\d+", k) and v for k, v in m["gestures"].items()), base
    assert all(NOTHING_NAME.search(n) for n in ["CMF Buds Pro 2", "Nothing Ear (a)", "Ear (stick)", "Nothing Headphone (1)"])
    assert not NOTHING_NAME.search("OnePlus Nord Buds 2r")
    print("ok", len(MODELS), "models")
