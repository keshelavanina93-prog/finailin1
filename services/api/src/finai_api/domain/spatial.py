"""Strict renderer geometry contract; no coordinate-system guessing."""

import math
from typing import Any


def validate_geometry(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {"type", "coordinates"}:
        raise ValueError("Geometry requires only type and WGS84 coordinates")
    kind, coordinates = value.get("type"), value.get("coordinates")
    points: list[list[float]] = []

    def point(item: Any) -> None:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("Positions require longitude and latitude")
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in item):
            raise ValueError("Coordinates must be finite numbers")
        if not -180 <= item[0] <= 180 or not -90 <= item[1] <= 90:
            raise ValueError("Coordinates must be WGS84 longitude/latitude")
        if len(points) >= 10000:
            raise ValueError("Geometry exceeds 10000 positions")
        points.append(item)

    if kind == "Point":
        point(coordinates)
    elif kind == "LineString":
        if not isinstance(coordinates, list) or len(coordinates) < 2:
            raise ValueError("LineString requires at least two positions")
        for item in coordinates:
            point(item)
    elif kind == "Polygon":
        if not isinstance(coordinates, list) or not coordinates:
            raise ValueError("Polygon requires rings")
        for ring in coordinates:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("Polygon rings require at least four positions and closure")
            for item in ring:
                point(item)
    else:
        raise ValueError("Supported geometry: Point, LineString, Polygon")
    if len(points) > 10000:
        raise ValueError("Geometry exceeds 10000 positions")
    return value


def geometry_bounds(value: dict[str, Any]) -> tuple[float, float, float, float]:
    coordinates = value["coordinates"]
    points = (
        [coordinates]
        if value["type"] == "Point"
        else coordinates
        if value["type"] == "LineString"
        else [p for ring in coordinates for p in ring]
    )
    return (
        min(p[0] for p in points),
        min(p[1] for p in points),
        max(p[0] for p in points),
        max(p[1] for p in points),
    )


def validate_geojson(value: Any) -> dict[str, Any]:
    import json

    if not isinstance(value, dict) or value.get("type") != "FeatureCollection":
        raise ValueError("Import requires a GeoJSON FeatureCollection")
    if set(value) - {"type", "features"}:
        raise ValueError("Only WGS84 FeatureCollections without CRS overrides are supported")
    features = value.get("features")
    if not isinstance(features, list) or not 1 <= len(features) <= 99:
        raise ValueError("Import requires between 1 and 99 features")
    if len(json.dumps(value, allow_nan=False).encode()) > 2_000_000:
        raise ValueError("Import exceeds 2 MB")
    codes = set()
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError("Each item must be a GeoJSON Feature")
        validate_geometry(feature.get("geometry"))
        properties = feature.get("properties")
        if not isinstance(properties, dict):
            raise ValueError("Each feature requires properties.name and properties.code")
        for key in ("name", "code"):
            if (
                not isinstance(properties.get(key), str)
                or not properties[key].strip()
                or len(properties[key]) > 200
            ):
                raise ValueError("Each feature requires name and code up to 200 characters")
        if properties["code"] in codes:
            raise ValueError("Feature codes must be unique within an import")
        codes.add(properties["code"])
    return value
