"""Read and validate the initial simulated city from version-controlled JSON."""

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.models.city import CityData

DEFAULT_CITY_PATH = Path(__file__).resolve().parents[2] / "data" / "san_jose_v1.json"


class CityDataError(ValueError):
    """A city seed file cannot be loaded safely."""


def _unique_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CityDataError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_city(path: Path = DEFAULT_CITY_PATH) -> CityData:
    """Load the full seed or raise a path and field-specific CityDataError."""

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CityDataError(f"Cannot read city data at {path}: {exc}") from exc
    except UnicodeError as exc:
        raise CityDataError(f"City data at {path} is not valid UTF-8: {exc}") from exc

    try:
        payload = json.loads(raw, object_pairs_hook=_unique_json_keys)
    except (json.JSONDecodeError, CityDataError) as exc:
        raise CityDataError(f"Invalid JSON in city data at {path}: {exc}") from exc

    try:
        return CityData.model_validate(payload)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'city'}: {error['msg']}"
            for error in exc.errors()
        )
        raise CityDataError(f"Invalid city data at {path}: {details}") from exc
