"""Tests for P3+ Multi-Agent Orchestrator."""

from __future__ import annotations

import asyncio
import sys
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch


class _ConfigStub:
    """Lightweight config stand-in for the orchestrator."""

    def __init__(
        self,
        enabled: bool = True,
        max_workers: int = 4,
        phase_timeout: float = 10.0,
        circuit_breaker_threshold: int = 3,
        circuit_breaker_window: int = 60,
    ):
        self.agent_orchestrator_enabled = enabled
        self.agent_orchestrator_max_workers = max_workers
        self.agent_orchestrator_phase_timeout = phase_timeout
        self.agent_orchestrator_circuit_breaker_threshold = circuit_breaker_threshold
        self.agent_orchestrator_circuit_breaker_window = circuit_breaker_window


class TestAgentOrchestrator(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the multi-agent orchestrator and its MCP integration."""

    def setUp(self) -> None:
        # Ensure deterministic fresh imports for each test.
        for mod in list(sys.modules):
            if mod in (
                "agent_orchestrator",
                "query_router",
                "chat_agentic",
                "agent_bus",
            ):
                del sys.modules[mod]

    def _patch_modules(
        self,
        *,
        classify_query: str = "vector",
        route_block: str = "RAG recall (memory): sample context",
        route_hits: list[dict[str, Any]] | None = None,
        coverage_gaps: list[str] | None = None,
        coverage_needs: bool = False,
        chat_agentic_enabled: bool = True,
        corroborated: int = 0,
        uncorroborated: int = 0,
        bus_enabled: bool = False,
        bus_delivered: int = 0,
    ) -> dict[str, Any]:
        """Build a mocked module set for the orchestrator."""
        route_hits = route_hits or []
        coverage_gaps = coverage_gaps or []

        query_router = MagicMock()
        query_router.classify_query = MagicMock(return_value=classify_query)
        query_router.route_retrieval = AsyncMock(
            return_value={
                "route": classify_query,
                "block": route_block,
                "hits": route_hits,
                "meta": {},
            }
        )
        query_router.VALID_ROUTES = (
            "vector",
            "graph",
            "spatial",
            "hybrid",
            "live",
        )

        chat_agentic = MagicMock()
        chat_agentic.chat_agentic_enabled = MagicMock(return_value=chat_agentic_enabled)
        chat_agentic.assess_coverage = MagicMock(
            return_value={
                "phase": "coverage",
                "char_count": len(route_block),
                "unique_sources": 1,
                "has_strong": True,
                "has_thin": False,
                "gaps": coverage_gaps,
                "needs_retrieve": coverage_needs,
            }
        )
        chat_agentic.apply_corroboration_tags = MagicMock(
            return_value=(
                route_block,
                {
                    "phase": "corroboration",
                    "source_count": 1,
                    "corroborated": corroborated,
                    "uncorroborated": uncorroborated,
                    "tagged_lines": corroborated + uncorroborated,
                },
            )
        )

        agent_bus = MagicMock()
        agent_bus.agent_bus_enabled = MagicMock(return_value=bus_enabled)
        agent_bus.publish_action = AsyncMock(
            return_value={"ok": True, "delivered": bus_delivered}
        )
        agent_bus.GLOBE_LAYER_KEYS = frozenset({"intelFt", "events"})
        agent_bus.AgentPublishBody = MagicMock()
        agent_bus.subscriber_count = MagicMock(return_value=0)

        return {
            "query_router": query_router,
            "chat_agentic": chat_agentic,
            "agent_bus": agent_bus,
        }

    async def test_disabled_returns_short_circuit(self) -> None:
        """When disabled, orchestrate returns a minimal disabled dict."""
        import agent_orchestrator

        with patch.object(
            agent_orchestrator, "get_config", return_value=_ConfigStub(enabled=False)
        ):
            result = await agent_orchestrator.orchestrate("what is happening")

        self.assertFalse(result["enabled"])
        self.assertEqual(result["query"], "what is happening")
        self.assertEqual(result["final_block"], "")
        self.assertEqual(result["hud_delivered"], 0)
        self.assertIn("circuit_breakers", result)

    async def test_route_classification_uses_provided_route(self) -> None:
        """If a route is provided, the orchestrator uses it without classifying."""
        import agent_orchestrator

        modules = self._patch_modules(
            classify_query="graph", route_block="graph context"
        )
        with patch.dict(
            sys.modules,
            {
                "query_router": modules["query_router"],
                "chat_agentic": modules["chat_agentic"],
                "agent_bus": modules["agent_bus"],
            },
        ), patch.object(
            agent_orchestrator, "get_config", return_value=_ConfigStub(enabled=True)
        ):
            result = await agent_orchestrator.orchestrate(
                "near Bangkok", route="spatial"
            )

        self.assertEqual(result["route"], "spatial")
        modules["query_router"].classify_query.assert_not_called()

    async def test_route_classification_falls_back_to_classifier(self) -> None:
        """Without an explicit route, classify_query is used."""
        import agent_orchestrator

        modules = self._patch_modules(
            classify_query="spatial", route_block="spatial context"
        )
        with patch.dict(
            sys.modules,
            {
                "query_router": modules["query_router"],
                "chat_agentic": modules["chat_agentic"],
                "agent_bus": modules["agent_bus"],
            },
        ), patch.object(
            agent_orchestrator, "get_config", return_value=_ConfigStub(enabled=True)
        ):
            result = await agent_orchestrator.orchestrate("within 50km of Bangkok")

        self.assertEqual(result["route"], "spatial")
        modules["query_router"].classify_query.assert_called_once()

    async def test_coverage_phase_present(self) -> None:
        """The trace always contains a coverage phase with timing."""
        import agent_orchestrator

        modules = self._patch_modules(route_block="context")
        with patch.dict(
            sys.modules,
            {
                "query_router": modules["query_router"],
                "chat_agentic": modules["chat_agentic"],
                "agent_bus": modules["agent_bus"],
            },
        ), patch.object(
            agent_orchestrator, "get_config", return_value=_ConfigStub(enabled=True)
        ):
            result = await agent_orchestrator.orchestrate("test")

        phases = [p["phase"] for p in result["phases"]]
        self.assertIn("coverage", phases)
        coverage = [p for p in result["phases"] if p["phase"] == "coverage"][0]
        self.assertIn("duration_ms", coverage)
        self.assertGreaterEqual(result["final_block_chars"], len("context"))

    async def test_retrieval_phase_triggered_by_gap(self) -> None:
        """A coverage gap triggers the retrieval agent."""
        import agent_orchestrator

        modules = self._patch_modules(
            route_block="thin",
            coverage_gaps=["block_too_short"],
            coverage_needs=True,
        )
        with patch.dict(
            sys.modules,
            {
                "query_router": modules["query_router"],
                "chat_agentic": modules["chat_agentic"],
                "agent_bus": modules["agent_bus"],
            },
        ), patch.object(
            agent_orchestrator, "get_config", return_value=_ConfigStub(enabled=True)
        ):
            result = await agent_orchestrator.orchestrate("test")

        phases = [p["phase"] for p in result["phases"]]
        self.assertIn("retrieval", phases)
        self.assertGreaterEqual(modules["query_router"].route_retrieval.call_count, 1)

    async def test_spatial_phase_for_spatial_route(self) -> None:
        """Spatial or hybrid route triggers the spatial agent."""
        import agent_orchestrator

        modules = self._patch_modules(
            classify_query="spatial", route_block="spatial context"
        )
        modules["query_router"].route_retrieval = AsyncMock(
            return_value={
                "route": "spatial",
                "block": "spatial context",
                "hits": [{"text": "Bangkok event"}],
                "meta": {},
            }
        )
        with patch.dict(
            sys.modules,
            {
                "query_router": modules["query_router"],
                "chat_agentic": modules["chat_agentic"],
                "agent_bus": modules["agent_bus"],
            },
        ), patch.object(
            agent_orchestrator, "get_config", return_value=_ConfigStub(enabled=True)
        ):
            result = await agent_orchestrator.orchestrate("near Bangkok")

        phases = [p["phase"] for p in result["phases"]]
        self.assertIn("spatial", phases)
        self.assertEqual(result["route"], "spatial")

    async def test_hybrid_route_triggers_spatial(self) -> None:
        """Hybrid route triggers the spatial agent."""
        import agent_orchestrator

        modules = self._patch_modules(
            classify_query="hybrid", route_block="hybrid context"
        )
        with patch.dict(
            sys.modules,
            {
                "query_router": modules["query_router"],
                "chat_agentic": modules["chat_agentic"],
                "agent_bus": modules["agent_bus"],
            },
        ), patch.object(
            agent_orchestrator, "get_config", return_value=_ConfigStub(enabled=True)
        ):
            result = await agent_orchestrator.orchestrate("who is near Bangkok")

        phases = [p["phase"] for p in result["phases"]]
        self.assertIn("spatial", phases)
        self.assertIn("coverage", phases)
        self.assertIn("corroboration", phases)
        self.assertIn("synthesis", phases)

    async def test_corroboration_phase_runs(self) -> None:
        """Corroboration agent tags are reflected in the trace."""
        import agent_orchestrator

        modules = self._patch_modules(
            route_block="[source] claim", corroborated=1, uncorroborated=0
        )
        with patch.dict(
            sys.modules,
            {
                "query_router": modules["query_router"],
                "chat_agentic": modules["chat_agentic"],
                "agent_bus": modules["agent_bus"],
            },
        ), patch.object(
            agent_orchestrator, "get_config", return_value=_ConfigStub(enabled=True)
        ):
            result = await agent_orchestrator.orchestrate("test")

        corro = [p for p in result["phases"] if p["phase"] == "corroboration"][0]
        self.assertEqual(corro["corroborated"], 1)
        self.assertEqual(corro["uncorroborated"], 0)

    async def test_fail_soft_on_route_retrieval_error(self) -> None:
        """An exception during route retrieval does not crash the pipeline."""
        import agent_orchestrator

        modules = self._patch_modules()
        modules["query_router"].route_retrieval = AsyncMock(
            side_effect=RuntimeError("RAG unavailable")
        )
        # Corroboration mock should pass through the block, not replace it
        modules["chat_agentic"].apply_corroboration_tags = MagicMock(
            side_effect=lambda b: (
                b,
                {
                    "phase": "corroboration",
                    "source_count": 0,
                    "corroborated": 0,
                    "uncorroborated": 0,
                    "tagged_lines": 0,
                },
            )
        )
        with patch.dict(
            sys.modules,
            {
                "query_router": modules["query_router"],
                "chat_agentic": modules["chat_agentic"],
                "agent_bus": modules["agent_bus"],
            },
        ), patch.object(
            agent_orchestrator, "get_config", return_value=_ConfigStub(enabled=True)
        ):
            result = await agent_orchestrator.orchestrate("test")

        self.assertTrue(result["enabled"])
        self.assertIn("initial_error", result)
        phases = [p["phase"] for p in result["phases"]]
        self.assertIn("coverage", phases)
        self.assertIn("synthesis", phases)

    async def test_fail_soft_on_chat_agentic_error(self) -> None:
        """An exception in chat_agentic coverage falls back to the thin heuristic."""
        import agent_orchestrator

        modules = self._patch_modules(route_block="short")
        modules["chat_agentic"].chat_agentic_enabled = MagicMock(return_value=True)
        modules["chat_agentic"].assess_coverage = MagicMock(
            side_effect=RuntimeError("coverage crash")
        )
        with patch.dict(
            sys.modules,
            {
                "query_router": modules["query_router"],
                "chat_agentic": modules["chat_agentic"],
                "agent_bus": modules["agent_bus"],
            },
        ), patch.object(
            agent_orchestrator, "get_config", return_value=_ConfigStub(enabled=True)
        ):
            result = await agent_orchestrator.orchestrate("test")

        self.assertTrue(result["enabled"])
        coverage = [p for p in result["phases"] if p["phase"] == "coverage"][0]
        self.assertIn("error", coverage)
        self.assertTrue(coverage["needs_retrieve"])

    async def test_hud_phase_publish_when_bus_enabled(self) -> None:
        """Phase events are published when the Agent Bus is enabled."""
        import agent_orchestrator

        modules = self._patch_modules(
            route_block="context", bus_enabled=True, bus_delivered=2
        )
        with patch.dict(
            sys.modules,
            {
                "query_router": modules["query_router"],
                "chat_agentic": modules["chat_agentic"],
                "agent_bus": modules["agent_bus"],
            },
        ), patch.object(
            agent_orchestrator, "get_config", return_value=_ConfigStub(enabled=True)
        ):
            result = await agent_orchestrator.orchestrate("test")

        self.assertGreater(result["hud_delivered"], 0)
        modules["agent_bus"].publish_action.assert_called()

    async def test_phase_timeout_metadata(self) -> None:
        """Phases that run include a duration_ms timing field."""
        import agent_orchestrator

        modules = self._patch_modules(route_block="context")
        with patch.dict(
            sys.modules,
            {
                "query_router": modules["query_router"],
                "chat_agentic": modules["chat_agentic"],
                "agent_bus": modules["agent_bus"],
            },
        ), patch.object(
            agent_orchestrator, "get_config", return_value=_ConfigStub(enabled=True)
        ):
            result = await agent_orchestrator.orchestrate("test")

        for phase in result["phases"]:
            self.assertIn("duration_ms", phase)
            self.assertIsInstance(phase["duration_ms"], int)

    async def test_phase_timeout_fires_and_fail_soft(self) -> None:
        """A slow phase is cancelled by timeout and the pipeline continues."""
        import agent_orchestrator

        modules = self._patch_modules(
            route_block="context",
        )
        modules["query_router"].route_retrieval = AsyncMock(
            side_effect=asyncio.sleep(60)
        )
        with patch.dict(
            sys.modules,
            {
                "query_router": modules["query_router"],
                "chat_agentic": modules["chat_agentic"],
                "agent_bus": modules["agent_bus"],
            },
        ), patch.object(
            agent_orchestrator,
            "get_config",
            return_value=_ConfigStub(enabled=True, phase_timeout=0.01),
        ):
            result = await agent_orchestrator.orchestrate("test")

        self.assertTrue(result["enabled"])
        self.assertIn("initial_error", result)

    async def test_circuit_breaker_opens_after_failures(self) -> None:
        """After repeated failures, the circuit breaker skips the agent."""
        import agent_orchestrator

        # Reset circuit state for determinism.
        agent_orchestrator._circuit_breakers.clear()

        modules = self._patch_modules(
            route_block="context",
            chat_agentic_enabled=True,
            corroborated=0,
            uncorroborated=0,
        )
        modules["chat_agentic"].assess_coverage = MagicMock(
            side_effect=RuntimeError("coverage crash")
        )
        cfg = _ConfigStub(
            enabled=True,
            circuit_breaker_threshold=2,
            circuit_breaker_window=60,
        )

        with patch.dict(
            sys.modules,
            {
                "query_router": modules["query_router"],
                "chat_agentic": modules["chat_agentic"],
                "agent_bus": modules["agent_bus"],
            },
        ), patch.object(agent_orchestrator, "get_config", return_value=cfg):
            # First call records one failure.
            await agent_orchestrator.orchestrate("test")
            # Second call should record the second failure and then skip.
            result = await agent_orchestrator.orchestrate("test")

        coverage_phases = [p for p in result["phases"] if p["phase"] == "coverage"]
        self.assertTrue(
            any(p.get("skipped") for p in coverage_phases)
            or any(p.get("error") for p in coverage_phases)
        )
        self.assertIn("coverage", result["circuit_breakers"])

    async def test_agent_status_structure(self) -> None:
        """agent_status returns the expected schema."""
        import agent_orchestrator

        modules = self._patch_modules(bus_enabled=False)
        with patch.dict(
            sys.modules,
            {
                "agent_bus": modules["agent_bus"],
            },
        ), patch.object(
            agent_orchestrator, "get_config", return_value=_ConfigStub(enabled=True)
        ):
            status = await agent_orchestrator.agent_status()

        self.assertIn("enabled", status)
        self.assertIn("max_workers", status)
        self.assertIn("phase_timeout", status)
        self.assertIn("circuit_breakers", status)
        self.assertIn("agent_bus_enabled", status)
        self.assertIn("supported_routes", status)
        self.assertIn("supported_phases", status)
        self.assertEqual(status["max_workers"], 4)
        self.assertEqual(status["phase_timeout"], 10.0)

    async def test_max_workers_config_respected(self) -> None:
        """The orchestrator reads max_workers from config."""
        import agent_orchestrator

        modules = self._patch_modules()
        with patch.dict(
            sys.modules,
            {
                "query_router": modules["query_router"],
                "chat_agentic": modules["chat_agentic"],
                "agent_bus": modules["agent_bus"],
            },
        ), patch.object(
            agent_orchestrator,
            "get_config",
            return_value=_ConfigStub(enabled=True, max_workers=16),
        ):
            _ = await agent_orchestrator.orchestrate("test")
            status = await agent_orchestrator.agent_status()

        self.assertEqual(status["max_workers"], 16)

    async def test_invalid_provided_route_falls_back(self) -> None:
        """An invalid route string falls back to the classifier."""
        import agent_orchestrator

        modules = self._patch_modules(
            classify_query="graph", route_block="graph context"
        )
        with patch.dict(
            sys.modules,
            {
                "query_router": modules["query_router"],
                "chat_agentic": modules["chat_agentic"],
                "agent_bus": modules["agent_bus"],
            },
        ), patch.object(
            agent_orchestrator, "get_config", return_value=_ConfigStub(enabled=True)
        ):
            result = await agent_orchestrator.orchestrate("test", route="invalid")

        self.assertEqual(result["route"], "graph")
        modules["query_router"].classify_query.assert_called_once()


class TestAgentBusPhaseAction(unittest.TestCase):
    """Tests for the Agent Bus agent_phase action validation."""

    def test_agent_phase_requires_title(self) -> None:
        """agent_phase actions without a title must raise HTTPException."""
        from agent_bus import AgentPublishBody, _validate_publish
        from fastapi import HTTPException

        body = AgentPublishBody(action="agent_phase", title="")
        with self.assertRaises(HTTPException) as ctx:
            _validate_publish(body)
        self.assertIn("title", str(ctx.exception.detail).lower())

    def test_agent_phase_accepts_title_and_lines(self) -> None:
        """agent_phase actions with a title pass validation."""
        from agent_bus import AgentPublishBody, _validate_publish

        body = AgentPublishBody(
            action="agent_phase", title="Coverage", lines=["route=vector"]
        )
        # Should not raise
        _validate_publish(body)


if __name__ == "__main__":
    unittest.main()
