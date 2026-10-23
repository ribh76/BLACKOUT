"""Load versioned dependency records and verify city asset references."""

import json
from pathlib import Path

from pydantic import ValidationError

from app.models.city import CityData
from app.models.dependency import DependencyData

DEFAULT_DEPENDENCY_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "san_jose_dependencies_v1.json"
)


class DependencyDataError(ValueError):
    """The dependency seed is missing, malformed, or inconsistent with the city."""


def load_dependencies(
    city: CityData, path: Path = DEFAULT_DEPENDENCY_PATH
) -> DependencyData:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DependencyDataError(
            f"Cannot read dependency data at {path}: {exc}"
        ) from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DependencyDataError(
            f"Invalid JSON in dependency data at {path}: {exc}"
        ) from exc

    try:
        data = DependencyData.model_validate(payload)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'dependencies'}: "
            f"{error['msg']}"
            for error in exc.errors()
        )
        raise DependencyDataError(
            f"Invalid dependency data at {path}: {details}"
        ) from exc

    if data.city_schema_version != city.schema_version:
        raise DependencyDataError(
            f"Dependency data at {path} targets city schema "
            f"{data.city_schema_version}, loaded city is {city.schema_version}"
        )

    node_ids = {node.id for node in city.nodes}
    for index, edge in enumerate(data.edges):
        if edge.provider_id not in node_ids:
            raise DependencyDataError(
                f"Dependency data at {path}, edges[{index}]: "
                f"unknown provider_id {edge.provider_id!r}"
            )
        if edge.dependent_id not in node_ids:
            raise DependencyDataError(
                f"Dependency data at {path}, edges[{index}]: "
                f"unknown dependent_id {edge.dependent_id!r}"
            )
    return data
