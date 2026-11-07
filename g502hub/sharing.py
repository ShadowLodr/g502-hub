"""Profiles as files people can share: one onboard profile, byte-exact, plus a readable summary."""

import json

from . import __version__, onboard

FORMAT = "g502-hub-profile"
VERSION = 1
# Files say which model they were made on; both use the same profile layout, so
# either imports either (the LIGHTSPEED's ID is its receiver one, cable or not)
DEVICES = {"G502 HERO": "046d:c08b", "G502 LIGHTSPEED": "046d:407f"}
DEVICE = DEVICES["G502 HERO"]
SUFFIX = ".g502profile"
BATTERY = 0x0C  # special function only the LIGHTSPEED has


class ShareError(ValueError):
    pass


def export(profile, model="G502 HERO"):
    """A JSON text for one onboard profile."""
    data = profile.encode()
    summary = {
        "name": profile.name,
        "report_rate_hz": profile.report_rate_hz,
        "dpi": [dpi for _, dpi in profile.dpi_levels()],
        "default_dpi_level": next((n for n, (s, _) in enumerate(profile.dpi_levels(), 1)
                                   if s == profile.default_dpi_index), None),
        "lighting": [led.describe() for led in profile.leds],
        "buttons": [b.describe() for b in profile.buttons[:11]],
        "gshift": [b.describe() for b in profile.gshift[:11]],
    }
    return json.dumps({"format": FORMAT, "version": VERSION, "device": DEVICES[model],
                       "app": f"G502 Hub {__version__}", "summary": summary,
                       "sector": data.hex()}, indent=2) + "\n"


def load(text, model="G502 HERO"):
    """(Profile, notes) from an exported file, for a `model` mouse. Notes explain
    anything that was changed."""
    try:
        doc = json.loads(text)
    except ValueError as e:
        raise ShareError(f"not a profile file ({e})") from None
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ShareError("not a G502 Hub profile file")
    if doc.get("version", 0) > VERSION:
        raise ShareError("made by a newer version of G502 Hub; update to import it")
    made_on = next((m for m, device in DEVICES.items() if device == doc.get("device")), None)
    if made_on is None:
        raise ShareError(f"made for another device ({doc.get('device')}), not a G502 HERO or LIGHTSPEED")
    try:
        data = bytes.fromhex(doc["sector"])
    except (KeyError, TypeError, ValueError):
        raise ShareError("the profile data is missing or damaged") from None
    if len(data) != 255 or not onboard.crc_ok(data):
        raise ShareError("the profile data is damaged (checksum mismatch)")
    profile = onboard.Profile.decode(data)
    notes = []
    # Macros live in other memory sectors that aren't part of the file
    for layer, bindings in (("", profile.buttons), ("G-Shift ", profile.gshift)):
        for i, b in enumerate(bindings):
            if isinstance(b, onboard.Macro):
                bindings[i] = onboard.Disabled()
                notes.append(f"{layer}button {i + 1} had a macro, which can't be shared, so it's disabled")
            elif model != "G502 LIGHTSPEED" and isinstance(b, onboard.Special) and b.function == BATTERY:
                bindings[i] = onboard.Disabled()
                notes.append(f"{layer}button {i + 1} showed the battery level, which the {model} "
                             "doesn't have, so it's disabled")
    if made_on != model:
        notes.insert(0, f"Made on a {made_on}; the settings carry over to the {model}")
    return profile, notes
