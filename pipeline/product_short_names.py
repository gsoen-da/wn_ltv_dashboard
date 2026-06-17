"""Short display names for product_group values used in Output 1 top-3 columns.

The mapping is stored in product_short_names.json next to this file so it can
be extended without touching code.  When the JSON does not exist yet, a default
set (seeded from the product mapping reference sheet) is written on first load.

Use report.py --out 1 to be prompted for any top-15 products that are missing
a mapping before the report runs.
"""
import json
from pathlib import Path

_PATH = Path(__file__).parent / "product_short_names.json"

_DEFAULTS: dict[str, str] = {
    "Vitamin D":                    "Vit D",
    "Magnesium":                    "Mag",
    "Ashwagandha":                  "Ash",
    "Fertility Support for Women":  "Fert W",
    "Pregnancy + New Mother Multi": "PNM",
    "Omega 3":                      "O3",
    "Breastfeeding Support":        "BF Sup",
    "Menopause Complex":            "Meno",
    "Collagen":                     "Collagen",
    "Weight Mgmt Support":          "WMS",
}


def load() -> dict[str, str]:
    """Return the full mapping, writing defaults to disk if the file doesn't exist."""
    if _PATH.exists():
        return json.loads(_PATH.read_text(encoding="utf-8"))
    save(_DEFAULTS)
    return dict(_DEFAULTS)


def save(mapping: dict[str, str]) -> None:
    _PATH.write_text(
        json.dumps(mapping, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def apply(name: str, mapping: dict[str, str]) -> str:
    """Return the short name for *name*, falling back to the full name."""
    return mapping.get(name, name)
