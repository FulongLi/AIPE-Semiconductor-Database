"""Controlled aliases, explicit units, and reviewable overrides; no value guessing."""

import re

from aipe_devices.normalizers.units import normalize

from .models import ColumnMapping

# semantic -> group, SI unit, accepted aliases
FIELDS = {
    "pulse_width": ("condition", "s", ("pulse_width", "Pulse Width")),
    "switching_frequency": ("condition", "Hz", ("switching_frequency", "fsw")),
    "td_on": ("switching", "s", ("td_on", "turn_on_delay")),
    "td_off": ("switching", "s", ("td_off", "turn_off_delay")),
    "tr": ("switching", "s", ("tr", "rise_time")),
    "tf": ("switching", "s", ("tf", "fall_time")),
    "dv_dt": ("switching", "V/s", ("dv_dt", "dv/dt")),
    "di_dt": ("switching", "A/s", ("di_dt", "di/dt")),
    "manufacturer": ("identity", None, ("manufacturer", "vendor")),
    "part_number": ("identity", None, ("part_number", "part", "device", "part number")),
    "device_id": ("identity", None, ("device_id",)),
    "technology": ("identity", None, ("technology",)),
    "junction_temperature": (
        "condition",
        "K",
        ("Tj", "T_j", "Junction Temp", "junction_temperature", "Temperature", "Temp"),
    ),
    "drain_current": ("condition", "A", ("Id", "I_D", "Drain Current", "Current", "drain_current")),
    "dc_bus_voltage": ("condition", "V", ("Vdc", "Vbus", "dc_bus_voltage")),
    "drain_source_voltage": ("condition", "V", ("drain_source_voltage", "Vds sweep")),
    "gate_resistance_on": ("condition", "Ohm", ("Rgon", "Rg_on", "gate_resistance_on")),
    "gate_resistance_off": ("condition", "Ohm", ("Rgoff", "Rg_off", "gate_resistance_off")),
    "gate_voltage_on": ("condition", "V", ("Vgon", "Vgs", "gate_voltage_on")),
    "gate_voltage_off": ("condition", "V", ("Vgoff", "gate_voltage_off")),
    "Eon": ("switching", "J", ("Eon", "turn_on_energy", "turn on energy")),
    "Eoff": ("switching", "J", ("Eoff", "turn_off_energy", "turn off energy")),
    "Err": ("switching", "J", ("Err", "reverse_recovery_energy")),
    "voltage_drop": ("conduction", "V", ("Vds", "Vce", "voltage_drop")),
    "rds_on": ("conduction", "Ohm", ("Rds_on", "Rdson", "Rds(on)")),
    "ciss": ("capacitance", "F", ("Ciss",)),
    "coss": ("capacitance", "F", ("Coss",)),
    "crss": ("capacitance", "F", ("Crss",)),
    "Eoss": ("capacitance", "J", ("Eoss",)),
    "qg_total": ("gate_charge", "C", ("Qg", "qg_total")),
}


def token(value):
    return re.sub(r"[\s_()\-]", "", value).casefold()


ALIASES = {token(a): semantic for semantic, (_, _, aliases) in FIELDS.items() for a in aliases}


def split_header(header):
    match = re.match(r"^(.*?)\s*[\[(]([^\[\]()]+)[\])]\s*$", header)
    # Rds(on) is a quantity name, not a unit annotation.
    if match and token(header) not in ALIASES:
        return match[1].strip(), match[2].strip()
    return header.strip(), None


def known_header(header):
    return token(split_header(str(header))[0]) in ALIASES


def map_column(table, column, overrides=None):
    name, unit = split_header(column)
    semantic = ALIASES.get(token(name))
    status = "high_confidence" if semantic else "unresolved"
    override = (overrides or {}).get(f"{table}.{column}", (overrides or {}).get(column))
    ignored = False
    if override is not None:
        status = "confirmed"
        if isinstance(override, str):
            semantic = ALIASES.get(token(override), override)
        elif isinstance(override, dict):
            ignored = override.get("ignore", False)
            semantic = override.get("semantic", semantic)
            semantic = ALIASES.get(token(semantic), semantic) if semantic else None
            unit = override.get("unit", unit)
        else:
            raise ValueError(f"Invalid override for {column}")
    reason = None
    if not ignored:
        if semantic not in FIELDS:
            status, reason = "unresolved", "Unknown semantic; explicit mapping or ignore required"
        elif FIELDS[semantic][1] is not None:
            if unit == "C" and semantic == "junction_temperature":
                unit = "degC"
            try:
                if not unit or normalize(1, unit).unit != FIELDS[semantic][1]:
                    raise ValueError("Missing or incompatible engineering unit")
            except ValueError:
                status, reason = "needs_confirmation", "Missing, unknown, or incompatible unit"
    return ColumnMapping(
        table=table,
        column=column,
        semantic=semantic,
        unit=unit,
        status=status,
        ignored=ignored,
        reason=reason,
    )


def map_table(table, overrides=None):
    """Vds is a sweep coordinate in an explicitly recognizable capacitance table."""
    from .models import TableMapping

    columns = tuple(map_column(table.name, c, overrides) for c in table.columns)
    capacitance = any(
        c.semantic in {"ciss", "coss", "crss", "Eoss"} and not c.ignored for c in columns
    )
    if capacitance:
        columns = tuple(
            c.model_copy(update={"semantic": "drain_source_voltage"})
            if token(split_header(c.column)[0]) == "vds" and c.status == "high_confidence"
            else c
            for c in columns
        )
    return TableMapping(table=table.name, columns=columns)
