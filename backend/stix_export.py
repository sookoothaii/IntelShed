"""STIX 2.1 export from FtM entities — read-only interop with TIP platforms.

Maps Follow-the-Money entity schemas to STIX 2.1 SDOs (SCOs where applicable):
    Person         → ThreatActor (if sanctions-linked) or Identity (individual)
    Organization   → Identity (organization)
    Event          → Campaign / Incident
    Address        → Location
    Mention        → ObservedData
    InternetDomain → DomainName (SCO)
    IpAddress      → IPv4Addr / IPv6Addr (SCO)
    Email          → EmailAddress (SCO)
    Phone          → Phone (SCO, STIX 2.1 extension)
    UserAccount    → UserAccount

Also exports MISP event JSON from FtM entities.

No external API calls. Pure read-only transform from DuckDB → JSON.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from structured_log import get_logger

log = get_logger(__name__)

# STIX 2.1 spec constants
_STIX_VERSION = "2.1"
_BUNDLE_TYPE = "bundle"
_DEFAULT_MARKING_REF = "marking-definition--misp"

# FtM schema → STIX SDO type mapping
_SCHEMA_MAP: dict[str, str] = {
    "Person": "threat-actor",
    "Organization": "identity",
    "Company": "identity",
    "LegalEntity": "identity",
    "Event": "campaign",
    "Incident": "incident",
    "Address": "location",
    "RealEstate": "location",
    "Mention": "observed-data",
    "Email": "email-addr",
    "CryptoWallet": "cryptocurrency-wallet",
    "UserAccount": "user-account",
    "Document": "report",
    "Article": "report",
}

# FtM property → STIX field mapping per SDO type
_PROP_MAP: dict[str, dict[str, str]] = {
    "threat-actor": {
        "name": "name",
        "alias": "aliases",
        "notes": "description",
        "email": "primary_email_addr",
        "country": "country",
    },
    "identity": {
        "name": "name",
        "alias": "aliases",
        "notes": "description",
        "country": "country",
        "registrationNumber": "registration_id",
        "website": "website",
    },
    "campaign": {
        "name": "name",
        "summary": "description",
        "notes": "description",
    },
    "incident": {
        "name": "name",
        "summary": "description",
        "notes": "description",
        "date": "first_seen",
        "endDate": "last_seen",
    },
    "location": {
        "name": "name",
        "street": "street_address",
        "city": "city",
        "country": "country",
        "latitude": "latitude",
        "longitude": "longitude",
        "notes": "description",
    },
    "observed-data": {
        "name": "name",
        "summary": "description",
        "notes": "description",
    },
    "report": {
        "name": "name",
        "summary": "description",
        "notes": "description",
        "publishedAt": "published",
        "url": "url",
    },
    "user-account": {
        "name": "user_id",
        "username": "account_login",
        "email": "email_address",
        "notes": "description",
    },
    "domain-name": {
        "name": "value",
    },
    "ipv4-addr": {
        "name": "value",
    },
    "email-addr": {
        "address": "value",
        "name": "value",
    },
    "cryptocurrency-wallet": {
        "address": "value",
        "cryptoAddress": "value",
        "currency": "currency",
    },
}

# STIX SDO types that are SCOs (Stix Cyber Observables) — go in "objects" but
# have no `created`/`modified` fields
_SCO_TYPES = {
    "domain-name",
    "ipv4-addr",
    "ipv6-addr",
    "email-addr",
    "phone-number",
    "cryptocurrency-wallet",
}


def _stix_id(stix_type: str, entity_id: str) -> str:
    """Deterministic STIX identifier from FtM entity ID.

    STIX 2.1 requires UUIDv5 for deterministic IDs. We use a namespace UUID
    derived from "worldbase" and the FtM entity ID.
    """
    namespace = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")
    return f"{stix_type}--{uuid.uuid5(namespace, entity_id)}"


def _stix_timestamp(iso_str: str | None) -> str | None:
    """Normalize an ISO timestamp string to STIX format (YYYY-MM-DDTHH:MM:SS.sssZ)."""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    except (ValueError, TypeError):
        return None


def _now_stix() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _map_properties(stix_type: str, ftm_props: dict[str, list[str]]) -> dict[str, Any]:
    """Map FtM property dict to STIX fields for the given SDO type."""
    prop_map = _PROP_MAP.get(stix_type, {})
    result: dict[str, Any] = {}
    for ftm_prop, values in ftm_props.items():
        stix_field = prop_map.get(ftm_prop)
        if not stix_field or not values:
            continue
        if stix_field in ("aliases",):
            result[stix_field] = list(values)
        elif stix_field in ("latitude", "longitude"):
            try:
                result[stix_field] = float(values[0])
            except (ValueError, TypeError):
                pass
        else:
            result[stix_field] = str(values[0])
    return result


def _entity_to_stix(entity: dict[str, Any]) -> dict[str, Any] | None:
    """Convert a single FtM entity dict to a STIX 2.1 SDO/SCO.

    Returns None if the schema has no STIX mapping.
    """
    schema = entity.get("schema", "")
    stix_type = _SCHEMA_MAP.get(schema)
    if not stix_type:
        return None

    entity_id = entity["id"]
    props = entity.get("properties", {})
    stix_obj: dict[str, Any] = {
        "type": stix_type,
        "id": _stix_id(stix_type, entity_id),
        "spec_version": _STIX_VERSION,
    }

    # Map properties
    mapped = _map_properties(stix_type, props)
    stix_obj.update(mapped)

    # Entity-level lat/lon (not in properties dict) → STIX location fields
    if stix_type == "location":
        if entity.get("lat") is not None:
            stix_obj.setdefault("latitude", entity["lat"])
        if entity.get("lon") is not None:
            stix_obj.setdefault("longitude", entity["lon"])

    # SDOs have created/modified; SCOs don't
    if stix_type not in _SCO_TYPES:
        created = _stix_timestamp(entity.get("first_seen"))
        modified = _stix_timestamp(entity.get("last_seen"))
        stix_obj["created"] = created or _now_stix()
        stix_obj["modified"] = modified or stix_obj["created"]

    # Add FtM provenance as external reference
    datasets = entity.get("datasets", [])
    if datasets:
        stix_obj["external_references"] = [
            {
                "source_name": "worldbase",
                "external_id": entity_id,
                "description": f"Datasets: {', '.join(datasets)}",
            }
        ]

    # Add labels from datasets
    if datasets:
        stix_obj["labels"] = [f"worldbase:{d}" for d in datasets]

    return stix_obj


def _edge_to_stix_relationship(
    edge: dict[str, Any], source_type: str, target_type: str
) -> dict[str, Any] | None:
    """Convert an FtM edge to a STIX 2.1 Relationship SDO."""
    source_id = edge.get("source_id")
    target_id = edge.get("target_id")
    kind = edge.get("kind", "related-to")
    if not source_id or not target_id:
        return None

    # Map edge kinds to STIX relationship types
    rel_type_map = {
        "owns": "owns",
        "controls": "controls",
        "located": "located-at",
        "participant": "participates-in",
        "payment": "transfers",
        "asset": "uses",
        "director": "works-for",
        "member": "member-of",
        "family": "related-to",
        "associate": "associated-with",
        "successor": "derived-from",
        "sameAs": "derived-from",
        "address": "located-at",
        "phone": "uses",
        "email": "uses",
        "website": "uses",
    }
    rel_type = rel_type_map.get(kind, "related-to")

    source_stix_id = _stix_id(source_type, source_id)
    target_stix_id = _stix_id(target_type, target_id)

    rel_obj: dict[str, Any] = {
        "type": "relationship",
        "id": _stix_id("relationship", f"{source_id}:{kind}:{target_id}"),
        "spec_version": _STIX_VERSION,
        "relationship_type": rel_type,
        "source_ref": source_stix_id,
        "target_ref": target_stix_id,
        "created": _stix_timestamp(edge.get("seen_at")) or _now_stix(),
        "modified": _stix_timestamp(edge.get("seen_at")) or _now_stix(),
    }
    if edge.get("confidence") is not None:
        rel_obj["confidence"] = int(max(0, min(100, edge["confidence"] * 100)))
    if edge.get("dataset"):
        rel_obj["external_references"] = [
            {
                "source_name": "worldbase",
                "description": f"Dataset: {edge['dataset']}",
            }
        ]
    return rel_obj


def export_entity_stix(entity_id: str) -> dict[str, Any]:
    """Export a single FtM entity (with neighbours + edges) as a STIX 2.1 bundle.

    Returns a STIX bundle dict with:
        type: "bundle"
        id: deterministic bundle ID
        objects: [SDOs, SCOs, Relationships]
    """
    import ftm_query

    entity_full = ftm_query.get_entity_full(entity_id)
    if not entity_full:
        return {
            "type": _BUNDLE_TYPE,
            "id": _stix_id("bundle", entity_id),
            "objects": [],
            "error": "entity not found",
        }

    objects: list[dict[str, Any]] = []

    # Map main entity
    main_stix = _entity_to_stix(entity_full)
    if main_stix:
        objects.append(main_stix)

    # Map neighbours
    neighbour_types: dict[str, str] = {}
    for neighbour in entity_full.get("neighbours", []):
        n_stix = _entity_to_stix(neighbour)
        if n_stix:
            objects.append(n_stix)
            neighbour_types[neighbour["id"]] = n_stix["type"]

    # Map edges as relationships
    main_type = main_stix["type"] if main_stix else "identity"
    for edge in entity_full.get("edges", []):
        source_id = edge.get("source_id")
        target_id = edge.get("target_id")
        source_type = (
            main_type
            if source_id == entity_id
            else neighbour_types.get(source_id, "identity")
        )
        target_type = (
            main_type
            if target_id == entity_id
            else neighbour_types.get(target_id, "identity")
        )
        rel = _edge_to_stix_relationship(edge, source_type, target_type)
        if rel:
            objects.append(rel)

    bundle_id = _stix_id("bundle", entity_id)
    return {
        "type": _BUNDLE_TYPE,
        "id": bundle_id,
        "objects": objects,
    }


def export_briefing_stix(briefing: dict[str, Any]) -> dict[str, Any]:
    """Export a briefing as a STIX 2.1 Report object with referenced entities.

    Returns a STIX bundle containing:
        - A Report SDO summarizing the briefing
        - SDOs/SCOs for each entity mentioned in insights/watch_items
        - Relationships between them
    """
    objects: list[dict[str, Any]] = []
    briefing_id = briefing.get("id", briefing.get("briefing_id", "unknown"))
    report_id = _stix_id("report", f"briefing:{briefing_id}")

    # Build report SDO
    insights = briefing.get("insights", [])
    watch_items = briefing.get("watch_items", [])
    summary_parts = []
    for ins in insights:
        if isinstance(ins, dict):
            summary_parts.append(ins.get("text", str(ins)))
        else:
            summary_parts.append(str(ins))

    report_obj: dict[str, Any] = {
        "type": "report",
        "id": report_id,
        "spec_version": _STIX_VERSION,
        "name": f"WorldBase Briefing {briefing.get('date', '')}",
        "description": " ".join(summary_parts)[:4096] or "No insights",
        "published": _stix_timestamp(briefing.get("date")) or _now_stix(),
        "created": _stix_timestamp(briefing.get("generated_at")) or _now_stix(),
        "modified": _stix_timestamp(briefing.get("generated_at")) or _now_stix(),
        "report_types": ["threat-report"],
        "object_refs": [],
    }
    objects.append(report_obj)

    # Export referenced entities
    seen_entity_ids: set[str] = set()
    for item in insights + watch_items:
        if not isinstance(item, dict):
            continue
        eid = item.get("entity_id")
        if not eid or eid in seen_entity_ids:
            continue
        seen_entity_ids.add(eid)
        entity_bundle = export_entity_stix(eid)
        for obj in entity_bundle.get("objects", []):
            if obj.get("type") == "bundle":
                continue
            # Avoid duplicates
            if not any(o.get("id") == obj.get("id") for o in objects):
                objects.append(obj)
                if obj.get("id"):
                    report_obj["object_refs"].append(obj["id"])

    bundle_id = _stix_id("bundle", f"briefing:{briefing_id}")
    return {
        "type": _BUNDLE_TYPE,
        "id": bundle_id,
        "objects": objects,
    }


def export_misp_event(entity_id: str) -> dict[str, Any]:
    """Export a FtM entity as a MISP event JSON.

    MISP event format (simplified):
        - Event: id, info, date, threat_level_id, analysis, attributes[]
        - Attributes: type, value, category, to_ids, comment
    """
    import ftm_query

    entity = ftm_query.get_entity_full(entity_id)
    if not entity:
        return {"error": "entity not found"}

    # Map FtM schema to MISP threat level
    threat_level_map = {
        "Person": "1",  # High
        "Organization": "2",  # Medium
        "Event": "3",  # Low
        "Incident": "1",
    }
    threat_level = threat_level_map.get(entity.get("schema", ""), "4")  # Undefined

    # Map FtM properties to MISP attributes
    attr_type_map = {
        "email": ("email-dst", "Network activity"),
        "ip": ("ip-dst", "Network activity"),
        "phone": ("phone-number", "Person"),
        "website": ("url", "Network activity"),
        "address": ("text", "Other"),
        "registrationNumber": ("text", "Other"),
        "idNumber": ("text", "Other"),
        "name": ("text", "Other"),
        "alias": ("text", "Other"),
    }

    attributes: list[dict[str, Any]] = []
    props = entity.get("properties", {})
    for prop, values in props.items():
        misp_type, category = attr_type_map.get(prop, ("text", "Other"))
        for v in values:
            attributes.append(
                {
                    "type": misp_type,
                    "category": category,
                    "value": str(v),
                    "to_ids": False,
                    "comment": f"From WorldBase dataset: {', '.join(entity.get('datasets', []))}",
                    "distribution": "0",
                }
            )

    # Add edges as related attributes
    for edge in entity.get("edges", []):
        target = edge.get("target_id", "")
        if target and target != entity_id:
            attributes.append(
                {
                    "type": "text",
                    "category": "Internal reference",
                    "value": f"{edge.get('kind', 'related-to')}:{target}",
                    "to_ids": False,
                    "comment": f"WorldBase edge (confidence: {edge.get('confidence', 'N/A')})",
                    "distribution": "0",
                }
            )

    event_id = hashlib.md5(entity_id.encode()).hexdigest()[:10]
    return {
        "Event": {
            "id": event_id,
            "info": entity.get("caption", entity_id),
            "date": (entity.get("first_seen") or _now_stix())[:10],
            "threat_level_id": threat_level,
            "analysis": "0",
            "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
            "distribution": "0",
            "Attribute": attributes,
            "Tag": [
                {"name": f"worldbase:{d}", "colour": "#0088cc"}
                for d in entity.get("datasets", [])
            ],
        }
    }
