"""Port of tests/test-clock-assign.js, exercising the Python port of
assignHours (custom_components/habird/assignment.py) against the exact same
fixtures, to catch any porting bug in the Hungarian-matching/hysteresis
logic. No pytest dependency required - run directly:

    python custom_components/habird/tests/test_assignment.py

(also pytest-discoverable, if pytest happens to be installed: every
function below is named test_*).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Load assignment.py directly by file path rather than as
# `custom_components.habird.assignment` - going through the package would
# execute custom_components/habird/__init__.py, which imports Home
# Assistant core and isn't installed in a plain checkout. assignment.py
# itself has zero HA dependencies (that's the point - see its docstring),
# so this keeps the test runnable with nothing but a plain Python 3.10+.
_SPEC = importlib.util.spec_from_file_location(
    "habird_assignment", Path(__file__).resolve().parents[1] / "assignment.py"
)
assignment = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = assignment  # dataclasses needs the module registered to resolve type hints
_SPEC.loader.exec_module(assignment)
assign_hours, clock_pos_of_hour = assignment.assign_hours, assignment.clock_pos_of_hour
hours_for_position = assignment.hours_for_position


def _row(base: float, spike: float, hours: list[int] | None = None) -> list[float]:
    row = [base] * 24
    for hour in hours or []:
        row[hour] = spike
    return row


def _species_set(out: dict) -> list[str | None]:
    return [entry.species for entry in out.values()]


def _unique_non_null(values: list[str | None]) -> tuple[int, int]:
    seen: set[str] = set()
    dupes = 0
    for value in values:
        if value is None:
            continue
        if value in seen:
            dupes += 1
        seen.add(value)
    return len(seen), dupes


def test_12_hour_fold_maps_midnight_and_noon_to_position_12() -> None:
    assert clock_pos_of_hour(0, 12) == 12
    assert clock_pos_of_hour(12, 12) == 12
    assert clock_pos_of_hour(1, 12) == 1
    assert clock_pos_of_hour(13, 12) == 1
    assert clock_pos_of_hour(23, 12) == 11


def test_24_hour_mode_midnight_is_position_24() -> None:
    assert clock_pos_of_hour(0, 24) == 24
    assert clock_pos_of_hour(6, 24) == 6
    assert clock_pos_of_hour(23, 24) == 23


def test_hours_for_position_inverts_clock_pos_of_hour() -> None:
    for positions in (12, 24):
        for hour in range(24):
            pos = clock_pos_of_hour(hour, positions)
            assert hour in hours_for_position(pos, positions)
    assert hours_for_position(12, 12) == [0, 12]
    assert hours_for_position(6, 12) == [6, 18]
    assert hours_for_position(6, 24) == [6]
    assert hours_for_position(24, 24) == [0]


def test_dawn_chorus_bird_lands_on_its_dawn_position() -> None:
    matrix = {
        "Turdus migratorius": _row(0, 40, [6]),  # robin: hour 6 only
        "Zenaida macroura": _row(3, 3, []),  # dove: flat all day
        "Corvus brachyrhynchos": _row(0, 20, [16]),  # crow: hour 16 only
        "Haemorhous mexicanus": _row(2, 2, []),
    }
    out = assign_hours(matrix, positions=12)
    assert out[6].species == "Turdus migratorius"
    assert out[6].source == "history"
    assert out[4].species == "Corvus brachyrhynchos"


def test_dominant_everywhere_species_takes_just_one_position() -> None:
    matrix = {"Passer domesticus": [50.0] * 24}  # everywhere, always
    names = [
        "Turdus migratorius", "Bubo virginianus", "Cathartes aura", "Hirundo rustica",
        "Corvus corax", "Cardinalis cardinalis", "Cyanocitta cristata", "Sitta carolinensis",
        "Poecile atricapillus", "Zenaida macroura", "Spinus tristis",
    ]
    for i, name in enumerate(names):
        matrix[name] = _row(0, 30, [i + 1])

    out = assign_hours(matrix, positions=12)
    sparrow_positions = [pos for pos, entry in out.items() if entry.species == "Passer domesticus"]
    assert len(sparrow_positions) == 1
    for i, name in enumerate(names):
        assert out[i + 1].species == name
    count, dupes = _unique_non_null(_species_set(out))
    assert dupes == 0
    assert count == 12


def test_sparse_data_borrow_fills_empty_hours_with_no_duplicates() -> None:
    matrix = {
        "Turdus migratorius": _row(0, 20, [6]),
        "Cardinalis cardinalis": _row(0, 18, [7]),
        "Cyanocitta cristata": _row(0, 15, [8]),
        "Sitta carolinensis": _row(0, 12, [9]),
        "Poecile atricapillus": _row(0, 9, [6, 7]),
        "Zenaida macroura": _row(0, 6, [8, 9]),
        "Spinus tristis": _row(0, 4, [7, 8]),
        "Melospiza melodia": _row(0, 3, [6, 9]),
        "Baeolophus bicolor": _row(0, 2, [7]),
        "Junco hyemalis": _row(0, 2, [8]),
        "Haemorhous mexicanus": _row(0, 1, [9]),
        "Dryobates pubescens": _row(0, 1, [6]),
    }
    out = assign_hours(matrix, positions=12)
    assert len(out) == 12
    count, dupes = _unique_non_null(_species_set(out))
    assert dupes == 0
    assert count == 12
    borrowed = [pos for pos, entry in out.items() if entry.source == "borrowed"]
    assert len(borrowed) > 0
    for pos in borrowed:
        assert out[pos].dim is True


def test_empty_matrix_with_small_pool_fallback_reused_when_exhausted() -> None:
    matrix = {
        "Turdus migratorius": [0.0] * 24,
        "Cardinalis cardinalis": [0.0] * 24,
        "Cyanocitta cristata": [0.0] * 24,
    }
    matrix["Turdus migratorius"][6] = 5
    matrix["Cardinalis cardinalis"][6] = 3
    matrix["Cyanocitta cristata"][6] = 1
    out = assign_hours(matrix, positions=12)
    assert len(out) == 12
    species = _species_set(out)
    first_three = set(species[:3])
    assert len(first_three) == 3
    reused = [pos for pos, entry in out.items() if entry.source == "reused"]
    assert len(reused) >= 9
    for pos in reused:
        assert out[pos].dim is True


def test_truly_empty_matrix_resolves_to_null_fallback_no_throw() -> None:
    out = assign_hours({}, positions=12)
    assert len(out) == 12
    for entry in out.values():
        assert entry.species is None
        assert entry.source == "fallback"


def test_pins_are_honored_and_never_double_assigned_elsewhere() -> None:
    matrix = {
        "Strix varia": _row(0, 30, [18, 19, 20]),  # would naturally win pos 6/7
        "Turdus migratorius": _row(0, 25, [6, 7]),
        "Cardinalis cardinalis": _row(0, 20, [6, 7, 8]),
        "Cyanocitta cristata": _row(0, 12, [9, 10]),
        "Sitta carolinensis": _row(0, 8, [11, 12]),
    }
    out = assign_hours(matrix, positions=12, pins={6: "Turdus migratorius", 7: "Strix varia"})
    assert out[6].species == "Turdus migratorius"
    assert out[6].source == "pinned"
    assert out[7].species == "Strix varia"
    assert out[7].source == "pinned"
    for pos, entry in out.items():
        if pos in (6, 7):
            continue
        assert entry.species != "Turdus migratorius"
        assert entry.species != "Strix varia"


def test_exclude_sci_keeps_an_art_less_species_out_of_every_code_path() -> None:
    matrix = {
        "Strix varia": _row(0, 30, [6]),  # would win position 6 outright
        "Turdus migratorius": _row(0, 5, [6]),  # weaker at hour 6
        "Cardinalis cardinalis": _row(0, 20, [7]),
        "Cyanocitta cristata": _row(0, 12, [8]),
    }
    out = assign_hours(matrix, positions=12, exclude_sci=["Strix varia"])
    assert out[6].species != "Strix varia"
    assert out[6].species == "Turdus migratorius"
    for entry in out.values():
        assert entry.species != "Strix varia"


def test_exclude_sci_does_not_override_an_explicit_pin() -> None:
    matrix = {"Strix varia": _row(0, 30, [6]), "Turdus migratorius": _row(0, 5, [7])}
    out = assign_hours(matrix, positions=12, pins={6: "Strix varia"}, exclude_sci=["Strix varia"])
    assert out[6].species == "Strix varia"
    assert out[6].source == "pinned"


def test_hysteresis_holds_an_incumbent_within_25_percent() -> None:
    matrix = {
        "Turdus migratorius": _row(0, 20, [6]),
        "Cardinalis cardinalis": _row(0, 22, [6]),
        "Cyanocitta cristata": _row(0, 30, [7]),
        "Sitta carolinensis": _row(0, 10, [8]),
    }
    held = assign_hours(matrix, positions=12, incumbents={6: "Turdus migratorius"}, hysteresis=0.25)
    assert held[6].species == "Turdus migratorius"

    matrix["Cardinalis cardinalis"] = _row(0, 200, [6])
    unseated = assign_hours(matrix, positions=12, incumbents={6: "Turdus migratorius"}, hysteresis=0.25)
    assert unseated[6].species == "Cardinalis cardinalis"


def test_12_mode_with_a_rich_pool_12_distinct_species() -> None:
    matrix = {}
    for hour in range(12):
        matrix[f"sp{hour}"] = _row(0, 10 + hour, [hour, hour + 12])
    out = assign_hours(matrix, positions=12)
    count, dupes = _unique_non_null(_species_set(out))
    assert count == 12
    assert dupes == 0


def test_24_mode_with_24_distinct_hour_specialists() -> None:
    matrix = {}
    for hour in range(24):
        matrix[f"sp{hour}"] = _row(0, 10, [hour])
    out = assign_hours(matrix, positions=24)
    assert len(out) == 24
    count, dupes = _unique_non_null(_species_set(out))
    assert count == 24
    assert dupes == 0
    for hour in range(24):
        pos = clock_pos_of_hour(hour, 24)
        assert out[pos].species == f"sp{hour}"


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn)]
    passed = 0
    for name, fn in tests:
        try:
            fn()
        except AssertionError as err:
            print(f"  FAIL {name}\n       {err}")
            sys.exit(1)
        else:
            print(f"  ok  {name}")
            passed += 1
    print(f"\nCLOCK-ASSIGN TESTS PASSED ({passed} checks)")
