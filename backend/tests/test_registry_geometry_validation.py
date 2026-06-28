"""Phase 2A — Geometry validation tests (Directive §12)."""
from __future__ import annotations

import pytest

from contexts.registry.domain.invariants import InvariantViolation
from contexts.registry.domain.value_objects import Geometry


def _valid_ring():
    return [[3.3, 6.5], [3.4, 6.5], [3.4, 6.6], [3.3, 6.6], [3.3, 6.5]]


def test_valid_polygon_accepted() -> None:
    g = Geometry(type="Polygon", coordinates=[_valid_ring()])
    assert g.to_dict()["type"] == "Polygon"


def test_must_be_polygon_type() -> None:
    with pytest.raises(ValueError):
        Geometry(type="Point", coordinates=[3.3, 6.5])


def test_unclosed_ring_rejected() -> None:
    ring = [[3.3, 6.5], [3.4, 6.5], [3.4, 6.6], [3.3, 6.6]]
    with pytest.raises(ValueError):
        Geometry(type="Polygon", coordinates=[ring])


def test_too_few_points_rejected() -> None:
    ring = [[3.3, 6.5], [3.4, 6.5], [3.3, 6.5]]
    with pytest.raises(ValueError):
        Geometry(type="Polygon", coordinates=[ring])


def test_out_of_range_coordinates_rejected() -> None:
    bad_ring = [[181.0, 0.0], [0.0, 0.0], [0.0, 1.0], [181.0, 0.0]]
    with pytest.raises(ValueError):
        Geometry(type="Polygon", coordinates=[bad_ring])
    bad_lat = [[0.0, 91.0], [1.0, 91.0], [1.0, 0.0], [0.0, 0.0], [0.0, 91.0]]
    with pytest.raises(ValueError):
        Geometry(type="Polygon", coordinates=[bad_lat])


def test_non_numeric_coordinate_rejected() -> None:
    bad_ring = [["lon", "lat"], [0.0, 0.0], [0.0, 1.0], ["lon", "lat"]]
    with pytest.raises(ValueError):
        Geometry(type="Polygon", coordinates=[bad_ring])
