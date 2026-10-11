"""Cell formatting shared by the bounded traffic workbook readers."""

import re
from decimal import Decimal, ROUND_HALF_UP

from openpyxl.cell.text import InlineFont


def font_snapshot(font, *, biff=False):
    if biff:
        return {"name": font.name, "size": font.height / 20,
                "bold": font.weight == 700, "italic": bool(font.italic),
                "strike": bool(font.struck_out), "underline": font.underline_type,
                "vertAlign": {0: None, 1: "superscript", 2: "subscript"}.get(font.escapement),
                "color_index": font.colour_index, "font_xml": None}
    from xml.etree.ElementTree import tostring
    return {"name": font.rFont if isinstance(font, InlineFont) else font.name,
            "size": font.sz, "bold": bool(font.b), "italic": bool(font.i),
            "strike": bool(font.strike), "underline": font.u,
            "vertAlign": font.vertAlign,
            "font_xml": tostring(font.to_tree(), encoding="unicode")}


def display_number(value, number_format):
    """Only formats verified for these tables; spacing suffix has no text."""
    if number_format in ("General", "@"):
        return str(value)
    match = re.fullmatch(r"0(?:\.(0+))?(?:_ )?", number_format)
    if not match:
        return None
    places = len(match[1] or "")
    return format(Decimal(str(value)).quantize(Decimal(1).scaleb(-places),
                                             rounding=ROUND_HALF_UP), f".{places}f")


def cell_snapshot(coordinate, value, value_type, number_format, font, runs):
    text = "" if value is None else str(value)
    display = display_number(value, number_format) if value_type == "n" else text
    return {"coordinate": coordinate, "raw_value": value, "raw_text": text,
            "value_type": value_type, "number_format": number_format,
            "display_text": display, "font": font, "rich_text": runs}
