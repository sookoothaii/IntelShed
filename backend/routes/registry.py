"""Register all WorldBase HTTP routers on the FastAPI app."""

from __future__ import annotations

import agent_bus
import ais_bridge
import anomaly_river
import blitzortung_bridge
import cams_bridge
import cap_bridge
import connectors.router as connectors_router
import credentials.router as credentials_router
import cve_bridge
import duckdb_fusion
import entsoe_bridge
import entity_resolution
import feed_ingest
import feeds_extra
import firewall_bridge
import flowsint_bridge
import ftm_store
import fusion_heatmap
import gdelt_bridge
import gibs_bridge
import globe_snapshot
import gtfs_ingestor
import humanitarian_bridge
import insights
import newsdata_bridge
import intel_ingest
import intel_graph_export
import intel_proximity
import intel_semantic_links
import markets_bridge
import nasa_firms
import node_sync
import osint_tools
import outages_bridge
import pegel_bridge
import pmtiles_bridge
import rag_memory
import sanctions_bridge
import situations
import smard_bridge
import stac_bridge
import stock_bridge
import traffic_bridge
import trust_router
import volcano_bridge
import webcam_bridge
import windy_bridge
import aircraft_trails
from routes import aircraft as aircraft_routes
from routes import chat as chat_routes
from routes import core_feeds
from routes import health as health_routes


def register_routers(app) -> None:
    app.include_router(agent_bus.router)
    app.include_router(core_feeds.router)
    app.include_router(chat_routes.router)
    app.include_router(health_routes.router)
    app.include_router(aircraft_routes.router)
    app.include_router(globe_snapshot.router)
    app.include_router(feeds_extra.router)
    app.include_router(node_sync.router)
    app.include_router(trust_router.router)
    app.include_router(osint_tools.router)
    app.include_router(nasa_firms.router)
    app.include_router(blitzortung_bridge.router)
    app.include_router(smard_bridge.router)
    app.include_router(stock_bridge.router)
    app.include_router(gtfs_ingestor.router)
    app.include_router(ais_bridge.router)
    app.include_router(cams_bridge.router)
    app.include_router(humanitarian_bridge.router)
    app.include_router(newsdata_bridge.router)
    app.include_router(entsoe_bridge.router)
    app.include_router(firewall_bridge.router)
    app.include_router(webcam_bridge.router)
    app.include_router(windy_bridge.router)
    app.include_router(cve_bridge.router)
    app.include_router(pegel_bridge.router)
    app.include_router(flowsint_bridge.router)
    app.include_router(gdelt_bridge.router)
    app.include_router(cap_bridge.router)
    app.include_router(anomaly_river.router)
    app.include_router(rag_memory.router)
    app.include_router(duckdb_fusion.router)
    app.include_router(gibs_bridge.router)
    app.include_router(outages_bridge.router)
    app.include_router(volcano_bridge.router)
    app.include_router(pmtiles_bridge.router)
    app.include_router(stac_bridge.router)
    app.include_router(sanctions_bridge.router)
    app.include_router(markets_bridge.router)
    app.include_router(aircraft_trails.router)
    app.include_router(fusion_heatmap.router)
    app.include_router(situations.router)
    app.include_router(insights.router)
    app.include_router(ftm_store.router)
    app.include_router(intel_ingest.router)
    app.include_router(intel_proximity.router)
    app.include_router(intel_semantic_links.router)
    app.include_router(intel_graph_export.router)
    app.include_router(entity_resolution.router)
    app.include_router(feed_ingest.router)
    app.include_router(credentials_router.router)
    app.include_router(connectors_router.router)
    app.include_router(traffic_bridge.router)
