"""Shared data structures and CSV input guards for hull-lines-dxf."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class Bundle:
    params: dict
    fields: list
    rows_original: list
    rows_effective: list
    stations: np.ndarray
    x: np.ndarray
    z: np.ndarray
    b: np.ndarray
    physical: bool
    x_note: str
    split: float
    origin_x: float
    levels: list
    profile_fields: list
    profile_rows: list
    profile_values: np.ndarray | None
    profile_half_widths: list
    deck_fields: list
    deck_rows: list
    deck_values: np.ndarray | None
    transom: dict
    correction_report: dict
    inventory: list


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or reader.fieldnames[0] != "station":
            raise ValueError(f"{path}: CSV first column must be station")
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError(f"{path}: duplicate CSV field names")
        rows = list(reader)
        if any(None in row or any(value is None for value in row.values()) for row in rows):
            raise ValueError(f"{path}: CSV row widths must match the header")
    return reader.fieldnames[1:], rows


def positive(value, name):
    number = float(value)
    if not np.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return number
