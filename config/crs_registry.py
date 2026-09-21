from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from pyproj import CRS, database
from pyproj.aoi import AreaOfInterest

DEFAULT_CRS = {
    "name": "WGS 84",
    "epsg": 4326,
    "description": "Global geographic coordinate reference system",
}

SUPPORTED_AUTHORITIES = ["EPSG", "ESRI", "NRCAN", "IGNF", "NKG", "OGC", "PROJ", "IAU_2015"]
CRS_TYPES = [
    "GEOGRAPHIC_2D_CRS",
    "GEOGRAPHIC_3D_CRS",
    "PROJECTED_CRS",
    "VERTICAL_CRS",
    "COMPOUND_CRS",
    "GEOCENTRIC_CRS",
    "ENGINEERING_CRS",
]


def _clean_user_input(value: str | int | None) -> str:
    return "" if value is None else str(value).strip()


def _normalise_epsg_text(value: str | int | None) -> int | None:
    text = _clean_user_input(value).upper()
    text = re.sub(r"^(?:EPSG\s*:\s*)", "", text)
    return int(text) if text.isdigit() else None


def parse_crs(value: str | int | CRS | None, allow_custom: bool = True) -> tuple[bool, str, CRS | None]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return True, "No CRS selected.", None
    try:
        if isinstance(value, CRS):
            return True, value.name, value
        text = _clean_user_input(value)
        epsg = _normalise_epsg_text(text)
        crs = CRS.from_epsg(epsg) if epsg is not None else CRS.from_user_input(text)
        if not allow_custom and epsg is None:
            auth = crs.to_authority()
            if not auth or auth[0].upper() != "EPSG":
                return False, "Only an EPSG CRS is allowed in this mode.", None
        return True, crs.name, crs
    except Exception as exc:
        return False, f"Invalid CRS: {exc}", None


def validate_epsg(epsg: int | str | None) -> tuple[bool, str, CRS | None]:
    return parse_crs(epsg, allow_custom=False)


def _units_for_crs(crs: CRS) -> str:
    try:
        units = [a.unit_name for a in crs.axis_info if a.unit_name]
        return ", ".join(sorted(set(units)))
    except Exception:
        return ""


def _authority_for_crs(crs: CRS) -> tuple[str, int | None]:
    try:
        auth = crs.to_authority()
        if auth:
            return f"{auth[0]}:{auth[1]}", int(auth[1]) if auth[0].upper() == "EPSG" else None
    except Exception:
        pass
    return "", None


def crs_summary(epsg: int | None) -> dict[str, Any]:
    if epsg is None:
        return {"epsg": None, "name": "Not specified", "type": "", "area": "", "authority": "", "units": ""}
    ok, message, crs = parse_crs(epsg, allow_custom=False)
    if not ok or crs is None:
        return {"epsg": epsg, "name": "Invalid CRS", "type": "", "area": message, "authority": "", "units": ""}
    authority, _ = _authority_for_crs(crs)
    return {
        "epsg": epsg,
        "name": crs.name,
        "type": crs.type_name,
        "area": crs.area_of_use.name if crs.area_of_use else "",
        "authority": authority,
        "units": _units_for_crs(crs),
    }


def crs_details(crs: CRS | None) -> dict[str, Any]:
    if crs is None:
        return {"name": "Not specified", "epsg": None, "authority": "", "type": "", "units": "", "area": "", "wkt": "", "projjson": "", "bounds": None, "datum": "", "ellipsoid": "", "coordinate_system": "", "area_description": ""}
    authority, epsg = _authority_for_crs(crs)
    bounds = None
    area_name = ""
    if crs.area_of_use:
        bounds = [crs.area_of_use.west, crs.area_of_use.south, crs.area_of_use.east, crs.area_of_use.north]
        area_name = crs.area_of_use.name or ""
    return {
        "name": crs.name,
        "epsg": epsg,
        "authority": authority,
        "type": crs.type_name,
        "units": _units_for_crs(crs),
        "area": area_name,
        "area_description": area_name,
        "bounds": bounds,
        "datum": crs.datum.name if crs.datum else "",
        "ellipsoid": crs.ellipsoid.name if crs.ellipsoid else "",
        "coordinate_system": crs.coordinate_system.name if crs.coordinate_system else "",
        "wkt": crs.to_wkt(),
        "projjson": crs.to_json(),
    }


@lru_cache(maxsize=16)
def _query_crs_info_cached(auth_name: str | None, pj_type: str | None, limit: int) -> tuple[dict[str, Any], ...]:
    rows = []
    kwargs = {"auth_name": auth_name, "allow_deprecated": False}
    if pj_type:
        kwargs["pj_types"] = pj_type
    for info in database.query_crs_info(**kwargs):
        rows.append({
            "authority": info.auth_name,
            "epsg": int(info.code) if str(info.code).isdigit() else info.code,
            "name": info.name,
            "type": info.type,
            "deprecated": info.deprecated,
            "area": info.area_of_use.name if info.area_of_use else "",
        })
        if len(rows) >= limit:
            break
    return tuple(rows)


def _crs_matches_query(info: dict[str, Any], query: str) -> bool:
    q = query.lower().replace("epsg:", "").strip()
    name = str(info.get("name", "")).lower()
    code = str(info.get("epsg", "")).lower()
    authority = str(info.get("authority", "")).lower()
    tokens = [t for t in re.split(r"[^a-z0-9]+", q) if t]
    if not tokens:
        return False
    if q == code or q == authority.lower() + ":" + code:
        return True
    return all(token in name or token in code or token in authority for token in tokens)


def _crs_search_score(info: dict[str, Any], query: str, prefer_wgs84: bool = True) -> int:
    q = query.lower().replace("epsg:", "").strip()
    name = str(info.get("name", "")).lower()
    code = str(info.get("epsg", "")).lower()
    score = 0
    if q == code:
        score += 1000
    if q in name:
        score += 300
    if "utm" in q and "utm" in name:
        score += 80
    if prefer_wgs84 and "wgs 84" in name:
        score += 120
    # For UTM searches, WGS 84 should rank above ETRS89 and other datums.
    if "utm" in q and "etrs89" in name:
        score -= 80
    if "utm" in q and "wgs 84" in name:
        score += 100
    if "utm" in q and "north" in q and "36n" in name.replace(" ", ""):
        score += 75
    if "zone" in q:
        for z in re.findall(r"\b(\d{1,2}[ns])\b", q.replace(" ", "")):
            if z in name.replace(" ", ""):
                score += 60
    return score


def search_epsg(
    query: str,
    limit: int = 30,
    authorities: list[str] | None = None,
    crs_type: str | None = None,
    prefer_wgs84: bool = True,
    area_of_interest: tuple[float, float, float, float] | None = None,
) -> list[dict[str, Any]]:
    query = _clean_user_input(query)
    if not query:
        return []
    authorities = authorities or ["EPSG"]
    out = []
    for auth in authorities:
        try:
            for info in _query_crs_info_cached(auth, crs_type, 20000):
                if not _crs_matches_query(info, query):
                    continue
                try:
                    crs = CRS.from_user_input(f"{info['authority']}:{info['epsg']}")
                    area_match = True
                    if area_of_interest and crs.area_of_use:
                        west, south, east, north = area_of_interest
                        a = crs.area_of_use
                        area_match = not (a.east < west or a.west > east or a.north < south or a.south > north)
                    if not area_match:
                        continue
                except Exception:
                    pass
                item = dict(info)
                item["_score"] = _crs_search_score(item, query, prefer_wgs84=prefer_wgs84)
                out.append(item)
        except Exception:
            continue

    out.sort(key=lambda x: (-x.get("_score", 0), str(x.get("name", ""))))
    for item in out:
        item.pop("_score", None)
    return out[:limit]

def browse_crs(authority: str = "EPSG", crs_type: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    try:
        return list(_query_crs_info_cached(authority, crs_type, limit))
    except Exception:
        return []


def suggest_utm_crs(longitude: float, latitude: float) -> list[dict[str, Any]]:
    """Suggest UTM CRSs for a location, preferring WGS 84 northern/southern equivalents."""
    try:
        aoi = AreaOfInterest(
            west_lon_degree=longitude,
            south_lat_degree=latitude,
            east_lon_degree=longitude,
            north_lat_degree=latitude,
        )
        items = list(database.query_utm_crs_info(area_of_interest=aoi, contains=True))
        is_north = latitude >= 0
        def rank(item):
            n = item.name.upper()
            score = 0
            if "WGS 84" in n:
                score += 300
            if "ETRS89" in n:
                score -= 50
            if ("NORTH" in n) == is_north:
                score += 25
            return -score
        items.sort(key=rank)
        return [
            {"authority": i.auth_name, "epsg": int(i.code), "name": i.name, "type": "PROJECTED_CRS"}
            for i in items
        ][:20]
    except Exception:
        return []

def transformer_preview(source: CRS | str | int, target: CRS | str | int, lon: float, lat: float) -> dict[str, Any]:
    from pyproj import Transformer
    src = CRS.from_user_input(source)
    dst = CRS.from_user_input(target)
    transformer = Transformer.from_crs(src, dst, always_xy=True)
    x, y = transformer.transform(float(lon), float(lat))
    return {"x": x, "y": y, "source": src.name, "target": dst.name}
