"""Register all WorldBase HTTP routers on the FastAPI app.

All imports are deferred inside ``register_routers`` so that module-level
side effects (DuckDB opens, HTTP clients, heavy ML loads) only fire when
the app is actually assembled — not when ``registry`` itself is imported.
This breaks circular-import chains and speeds up cold startup.
"""

from __future__ import annotations


def register_routers(app) -> None:
    # Core + routes package
    from routes import aircraft as aircraft_routes
    from routes import chat as chat_routes
    from routes import core_feeds
    from routes import health as health_routes

    # Bridge / feature modules
    import agent_bus
    import ais_bridge
    import aircraft_trails
    import anomaly_river
    import blitzortung_bridge
    import cams_bridge
    import cap_bridge
    import connectors.router as connectors_router
    import credentials.router as credentials_router
    import cve_bridge
    import darkweb_bridge
    import domain_intel
    import identity_osint
    import onion_directory
    import ransomware_tracker
    import thai_opendata
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
    import intel_graph_export
    import intel_ingest
    import intel_proximity
    import intel_semantic_links
    from routes import intel_stix as intel_stix_routes
    import markets_bridge
    import model_cookbook
    import nasa_firms
    import newsdata_bridge
    import node_sync
    import osint_tools
    import outages_bridge
    import pegel_bridge
    import pmtiles_bridge
    import rag_memory
    import sanctions_bridge
    import satellite_change
    import situations
    import smard_bridge
    import stac_bridge
    import stock_bridge
    import telegram_bridge
    import traffic_bridge
    import trust_router
    import volcano_bridge
    import webcam_bridge
    import windy_bridge

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
    app.include_router(darkweb_bridge.router)
    app.include_router(ransomware_tracker.router)
    app.include_router(domain_intel.router)
    app.include_router(identity_osint.router)
    app.include_router(thai_opendata.router)
    app.include_router(onion_directory.router)
    app.include_router(telegram_bridge.router)
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
    app.include_router(satellite_change.router)
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
    app.include_router(intel_stix_routes.router)
    app.include_router(entity_resolution.router)
    app.include_router(feed_ingest.router)
    app.include_router(credentials_router.router)
    app.include_router(connectors_router.router)
    app.include_router(traffic_bridge.router)
    app.include_router(model_cookbook.router)
    from routes import admin as admin_routes
    from routes import duckdb_queue as duckdb_queue_routes
    from routes import metrics as metrics_routes
    from routes import telemetry as telemetry_routes

    app.include_router(duckdb_queue_routes.router)
    app.include_router(admin_routes.router)
    app.include_router(metrics_routes.router)
    app.include_router(telemetry_routes.router)
    from routes import quota as quota_routes

    app.include_router(quota_routes.router)
    from routes import auth as auth_routes
    from routes import briefing_pipeline as briefing_pipeline_routes
    from routes import config as config_routes

    app.include_router(auth_routes.router)
    app.include_router(briefing_pipeline_routes.router)
    app.include_router(config_routes.router)
    import ws_gateway as ws_routes

    app.include_router(ws_routes.router)
