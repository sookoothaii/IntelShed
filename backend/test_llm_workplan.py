"""Tests for P1 Blackboard, P7 Personas, P3 Evidence Chains, P2 Report Schema, P4 Conflict Detection."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# P1 — Blackboard tests
# ---------------------------------------------------------------------------


class TestBlackboard(unittest.TestCase):
    """Tests for the shared blackboard data structure."""

    def test_create_empty_blackboard(self) -> None:
        from agent_blackboard import Blackboard

        bb = Blackboard(query="test query")
        self.assertEqual(bb.query, "test query")
        self.assertEqual(bb.route, "vector")
        self.assertEqual(bb.extracted_entities, [])
        self.assertEqual(bb.evidence_registry, [])
        self.assertEqual(bb.claim_candidates, [])
        self.assertEqual(bb.conflicts, [])

    def test_add_evidence_assigns_ids(self) -> None:
        from agent_blackboard import Blackboard

        bb = Blackboard(query="test")
        e1 = bb.add_evidence(
            source="gdelt", text="protest in Bangkok", provenance_score=0.8
        )
        e2 = bb.add_evidence(source="usgs", text="M4.5 quake", provenance_score=0.9)
        self.assertEqual(e1.id, "[EVIDENCE-001]")
        self.assertEqual(e2.id, "[EVIDENCE-002]")
        self.assertEqual(len(bb.evidence_registry), 2)

    def test_evidence_confidence_mapping(self) -> None:
        from agent_blackboard import Blackboard

        bb = Blackboard(query="test")
        high = bb.add_evidence(source="usgs", text="quake", provenance_score=0.9)
        med = bb.add_evidence(source="gdelt", text="protest", provenance_score=0.6)
        low = bb.add_evidence(source="blog", text="rumor", provenance_score=0.3)
        self.assertEqual(high.confidence, "HIGH")
        self.assertEqual(med.confidence, "MEDIUM")
        self.assertEqual(low.confidence, "LOW")

    def test_evidence_by_id(self) -> None:
        from agent_blackboard import Blackboard

        bb = Blackboard(query="test")
        bb.add_evidence(source="gdelt", text="event", provenance_score=0.7)
        found = bb.evidence_by_id("[EVIDENCE-001]")
        self.assertIsNotNone(found)
        self.assertEqual(found.source, "gdelt")
        none = bb.evidence_by_id("[EVIDENCE-999]")
        self.assertIsNone(none)

    def test_add_entity(self) -> None:
        from agent_blackboard import Blackboard

        bb = Blackboard(query="test")
        ent = bb.add_entity("Bangkok", entity_type="location", lat=13.75, lon=100.5)
        self.assertEqual(ent.name, "Bangkok")
        self.assertEqual(ent.entity_type, "location")
        self.assertEqual(len(bb.extracted_entities), 1)

    def test_add_claim(self) -> None:
        from agent_blackboard import Blackboard

        bb = Blackboard(query="test")
        c = bb.add_claim(
            "protest occurred", confidence="MEDIUM", supporting_ids=["[EVIDENCE-001]"]
        )
        self.assertEqual(c.claim, "protest occurred")
        self.assertFalse(c.uncorroborated)
        self.assertEqual(len(bb.claim_candidates), 1)

    def test_add_conflict(self) -> None:
        from agent_blackboard import Blackboard

        bb = Blackboard(query="test")
        bb.add_conflict(
            "[EVIDENCE-001]", "[EVIDENCE-002]", "existence", "conflicting reports"
        )
        self.assertEqual(len(bb.conflicts), 1)
        self.assertEqual(bb.conflicts[0].conflict_type, "existence")

    def test_temporal_timeline_sorted(self) -> None:
        from agent_blackboard import Blackboard

        bb = Blackboard(query="test")
        bb.add_evidence(
            source="b",
            text="later event",
            retrieved_at="2026-06-27T12:00:00Z",
            provenance_score=0.7,
        )
        bb.add_evidence(
            source="a",
            text="earlier event",
            retrieved_at="2026-06-27T06:00:00Z",
            provenance_score=0.7,
        )
        timeline = bb.temporal_timeline()
        self.assertEqual(len(timeline), 2)
        self.assertIn("earlier", timeline[0]["event"])

    def test_temporal_timeline_empty(self) -> None:
        from agent_blackboard import Blackboard

        bb = Blackboard(query="test")
        bb.add_evidence(source="a", text="no timestamp", provenance_score=0.5)
        timeline = bb.temporal_timeline()
        self.assertEqual(timeline, [])

    def test_condensed_state(self) -> None:
        from agent_blackboard import Blackboard

        bb = Blackboard(query="test", route="spatial")
        bb.add_evidence(source="gdelt", text="event", provenance_score=0.7)
        bb.add_entity("Bangkok")
        bb.add_claim("something happened")
        bb.add_conflict("[EVIDENCE-001]", "[EVIDENCE-002]", "temporal", "time mismatch")
        condensed = bb.condensed()
        self.assertEqual(condensed["query"], "test")
        self.assertEqual(condensed["route"], "spatial")
        self.assertEqual(condensed["entity_count"], 1)
        self.assertEqual(condensed["evidence_count"], 1)
        self.assertEqual(condensed["claim_count"], 1)
        self.assertEqual(condensed["conflict_count"], 1)
        self.assertIn("[EVIDENCE-001]", condensed["evidence_ids"])

    def test_extract_entities_from_query(self) -> None:
        from agent_blackboard import extract_entities_from_query

        entities = extract_entities_from_query(
            "Analyze earthquake near Bangkok Thailand"
        )
        types = [e.entity_type for e in entities]
        self.assertIn("event", types)
        names = [e.name.lower() for e in entities]
        self.assertIn("earthquake", names)

    def test_extract_entities_empty(self) -> None:
        from agent_blackboard import extract_entities_from_query

        self.assertEqual(extract_entities_from_query(""), [])

    def test_evidence_block_to_text(self) -> None:
        from agent_blackboard import Blackboard, evidence_block_to_text

        bb = Blackboard(query="test")
        bb.add_evidence(
            source="usgs",
            text="M4.5 quake near Bangkok",
            provenance_score=0.9,
            url="https://example.com",
        )
        text = evidence_block_to_text(bb)
        self.assertIn("[EVIDENCE-001]", text)
        self.assertIn("usgs", text)
        self.assertIn("HIGH", text)

    def test_evidence_block_empty(self) -> None:
        from agent_blackboard import Blackboard, evidence_block_to_text

        bb = Blackboard(query="test")
        self.assertEqual(evidence_block_to_text(bb), "")

    def test_conflicts_block_to_text(self) -> None:
        from agent_blackboard import Blackboard, conflicts_block_to_text

        bb = Blackboard(query="test")
        bb.add_conflict(
            "[EVIDENCE-001]", "[EVIDENCE-002]", "existence", "conflicting reports"
        )
        text = conflicts_block_to_text(bb)
        self.assertIn("CONFLICTING EVIDENCE", text)
        self.assertIn("[EVIDENCE-001]", text)
        self.assertIn("INSTRUCTION", text)

    def test_conflicts_block_empty(self) -> None:
        from agent_blackboard import Blackboard, conflicts_block_to_text

        bb = Blackboard(query="test")
        self.assertEqual(conflicts_block_to_text(bb), "")

    def test_timeline_block_to_text(self) -> None:
        from agent_blackboard import Blackboard, timeline_block_to_text

        bb = Blackboard(query="test")
        bb.add_evidence(
            source="a",
            text="event",
            retrieved_at="2026-06-27T06:00:00Z",
            provenance_score=0.7,
        )
        text = timeline_block_to_text(bb)
        self.assertIn("TEMPORAL TIMELINE", text)
        self.assertIn("2026-06-27", text)

    def test_confidence_to_score(self) -> None:
        from agent_blackboard import confidence_to_score

        self.assertAlmostEqual(confidence_to_score("HIGH"), 0.9)
        self.assertAlmostEqual(confidence_to_score("MEDIUM"), 0.65)
        self.assertAlmostEqual(confidence_to_score("LOW"), 0.3)


# ---------------------------------------------------------------------------
# P7 — Persona tests
# ---------------------------------------------------------------------------


class TestPersonas(unittest.TestCase):
    """Tests for agent role personas."""

    def test_persona_for_each_phase(self) -> None:
        import agent_orchestrator

        for phase in ("coverage", "retrieval", "spatial", "corroboration", "synthesis"):
            persona = agent_orchestrator.persona_prefix(phase)
            self.assertTrue(len(persona) > 10, f"Persona for {phase} is too short")

    def test_persona_unknown_phase_empty(self) -> None:
        import agent_orchestrator

        self.assertEqual(agent_orchestrator.persona_prefix("unknown"), "")

    def test_coverage_persona_mentions_osint(self) -> None:
        import agent_orchestrator

        self.assertIn("OSINT", agent_orchestrator.persona_prefix("coverage"))

    def test_synthesis_persona_mentions_evidence(self) -> None:
        import agent_orchestrator

        self.assertIn(
            "evidence", agent_orchestrator.persona_prefix("synthesis").lower()
        )

    def test_corroboration_persona_mentions_red_team(self) -> None:
        import agent_orchestrator

        self.assertIn(
            "red-team", agent_orchestrator.persona_prefix("corroboration").lower()
        )


# ---------------------------------------------------------------------------
# P4 — Conflict detection tests
# ---------------------------------------------------------------------------


class TestConflictDetection(unittest.TestCase):
    """Tests for source conflict detection."""

    def _make_evidence(
        self,
        id: str,
        text: str,
        source: str = "gdelt",
        retrieved_at: str = "",
        provenance_score: float = 0.7,
    ):
        from agent_blackboard import EvidenceItem

        return EvidenceItem(
            id=id,
            source=source,
            text=text,
            retrieved_at=retrieved_at,
            provenance_score=provenance_score,
        )

    def test_no_conflicts_with_single_item(self) -> None:
        from conflict_detection import detect_conflicts

        items = [self._make_evidence("[EVIDENCE-001]", "event in Bangkok")]
        self.assertEqual(detect_conflicts(items), [])

    def test_no_conflicts_with_unrelated_items(self) -> None:
        from conflict_detection import detect_conflicts

        items = [
            self._make_evidence("[EVIDENCE-001]", "earthquake in Japan"),
            self._make_evidence("[EVIDENCE-002]", "protest in Venezuela"),
        ]
        self.assertEqual(detect_conflicts(items), [])

    def test_existence_conflict_detected(self) -> None:
        from conflict_detection import detect_conflicts

        items = [
            self._make_evidence(
                "[EVIDENCE-001]", "Major protest in Bangkok reported", source="gdelt"
            ),
            self._make_evidence(
                "[EVIDENCE-002]",
                "No major unrest in Bangkok reported",
                source="newsdata",
            ),
        ]
        conflicts = detect_conflicts(items)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["conflict_type"], "existence")
        self.assertIn("Bangkok", conflicts[0]["description"])

    def test_temporal_conflict_detected(self) -> None:
        from conflict_detection import detect_conflicts

        items = [
            self._make_evidence(
                "[EVIDENCE-001]",
                "Bangkok protest event",
                retrieved_at="2026-06-27T06:00:00Z",
            ),
            self._make_evidence(
                "[EVIDENCE-002]",
                "Bangkok protest event",
                retrieved_at="2026-06-28T12:00:00Z",
            ),
        ]
        conflicts = detect_conflicts(items)
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["conflict_type"], "temporal")

    def test_temporal_conflict_not_triggered_under_24h(self) -> None:
        from conflict_detection import detect_conflicts

        items = [
            self._make_evidence(
                "[EVIDENCE-001]",
                "Bangkok protest event",
                retrieved_at="2026-06-27T06:00:00Z",
            ),
            self._make_evidence(
                "[EVIDENCE-002]",
                "Bangkok protest event",
                retrieved_at="2026-06-27T18:00:00Z",
            ),
        ]
        conflicts = detect_conflicts(items)
        # 12h difference — should not trigger
        temporal = [c for c in conflicts if c["conflict_type"] == "temporal"]
        self.assertEqual(temporal, [])

    def test_conflicts_capped_at_5(self) -> None:
        from conflict_detection import detect_conflicts

        items = []
        for i in range(12):
            items.append(
                self._make_evidence(
                    f"[EVIDENCE-{i+1:03d}]",
                    f"Bangkok event report {'no ' if i % 2 else ''}major incident",
                    source=f"source_{i}",
                )
            )
        conflicts = detect_conflicts(items)
        self.assertLessEqual(len(conflicts), 5)

    def test_conflicts_sorted_by_severity(self) -> None:
        from conflict_detection import detect_conflicts

        items = [
            self._make_evidence(
                "[EVIDENCE-001]",
                "Bangkok protest reported",
                source="gdelt",
                provenance_score=0.5,
            ),
            self._make_evidence(
                "[EVIDENCE-002]",
                "No Bangkok protest reported",
                source="newsdata",
                provenance_score=0.5,
            ),
            self._make_evidence(
                "[EVIDENCE-003]",
                "Bangkok event confirmed",
                source="usgs",
                provenance_score=0.9,
            ),
            self._make_evidence(
                "[EVIDENCE-004]",
                "No Bangkok event confirmed",
                source="hdx",
                provenance_score=0.8,
            ),
        ]
        conflicts = detect_conflicts(items)
        if len(conflicts) >= 2:
            self.assertGreaterEqual(conflicts[0]["severity"], conflicts[1]["severity"])

    def test_no_cross_feed_severity_conflicts(self) -> None:
        """Cross-feed severity deltas should NOT produce conflicts."""
        from conflict_detection import detect_conflicts

        items = [
            self._make_evidence(
                "[EVIDENCE-001]", "M4.5 earthquake near Bangkok", source="usgs"
            ),
            self._make_evidence(
                "[EVIDENCE-002]", "Bangkok earthquake mentioned", source="gdelt"
            ),
        ]
        conflicts = detect_conflicts(items)
        # Both affirm the same event — no conflict
        self.assertEqual(conflicts, [])


# ---------------------------------------------------------------------------
# P2 — Report schema tests
# ---------------------------------------------------------------------------


class TestReportSchema(unittest.TestCase):
    """Tests for structured JSON report schema and regex fallback parser."""

    def test_extract_json_plain(self) -> None:
        from report_schema import extract_json

        text = '{"key_findings": ["test"], "evidence_table": [], "assessment": "ok"}'
        result = extract_json(text)
        self.assertIsNotNone(result)
        self.assertEqual(result["key_findings"], ["test"])

    def test_extract_json_markdown_fence(self) -> None:
        from report_schema import extract_json

        text = 'Here is the report:\n```json\n{"key_findings": ["a"], "evidence_table": [], "assessment": "x"}\n```\nDone.'
        result = extract_json(text)
        self.assertIsNotNone(result)
        self.assertEqual(result["key_findings"], ["a"])

    def test_extract_json_trailing_prose(self) -> None:
        from report_schema import extract_json

        text = '{"key_findings": ["a"], "evidence_table": [], "assessment": "x"} I hope this helps.'
        result = extract_json(text)
        self.assertIsNotNone(result)
        self.assertEqual(result["assessment"], "x")

    def test_extract_json_trailing_commas(self) -> None:
        from report_schema import extract_json

        text = '{"key_findings": ["a",], "evidence_table": [], "assessment": "x",}'
        result = extract_json(text)
        self.assertIsNotNone(result)
        self.assertEqual(result["key_findings"], ["a"])

    def test_extract_json_missing_mandatory_fields_filled(self) -> None:
        from report_schema import extract_json

        text = '{"key_findings": ["a"]}'
        result = extract_json(text)
        self.assertIsNotNone(result)
        self.assertIn("evidence_table", result)
        self.assertIn("assessment", result)
        self.assertEqual(result["evidence_table"], [])

    def test_extract_json_invalid_returns_none(self) -> None:
        from report_schema import extract_json

        result = extract_json("this is not json at all")
        self.assertIsNone(result)

    def test_extract_json_empty(self) -> None:
        from report_schema import extract_json

        self.assertIsNone(extract_json(""))
        self.assertIsNone(extract_json("   "))

    def test_line_by_line_parse(self) -> None:
        from report_schema import extract_json

        text = """KEY FINDINGS: protest in Bangkok
- roads blocked
ASSESSMENT: situation is tense
RECOMMENDED ACTIONS: avoid downtown"""
        result = extract_json(text)
        self.assertIsNotNone(result)
        self.assertIn("key_findings", result)
        self.assertIn("assessment", result)

    def test_format_report_as_text(self) -> None:
        from report_schema import format_report_as_text

        report = {
            "key_findings": ["finding 1", "finding 2"],
            "evidence_table": [
                {"claim": "test claim", "source": "gdelt", "confidence": "HIGH"}
            ],
            "assessment": "test assessment",
        }
        text = format_report_as_text(report)
        self.assertIn("KEY FINDINGS", text)
        self.assertIn("finding 1", text)
        self.assertIn("EVIDENCE TABLE", text)
        self.assertIn("ASSESSMENT", text)
        self.assertIn("test assessment", text)

    def test_format_report_empty(self) -> None:
        from report_schema import format_report_as_text

        text = format_report_as_text({})
        # Should not crash, may be empty
        self.assertIsInstance(text, str)

    def test_build_report_from_blackboard(self) -> None:
        from agent_blackboard import Blackboard
        from report_schema import build_report_from_blackboard

        bb = Blackboard(query="test")
        bb.add_evidence(
            source="usgs",
            text="M4.5 quake",
            provenance_score=0.9,
            retrieved_at="2026-06-27T06:00:00Z",
        )
        bb.add_claim(
            "quake occurred", confidence="HIGH", supporting_ids=["[EVIDENCE-001]"]
        )
        bb.add_conflict("[EVIDENCE-001]", "[EVIDENCE-002]", "existence", "conflict")
        report = build_report_from_blackboard(bb)
        self.assertIn("key_findings", report)
        self.assertEqual(len(report["evidence_table"]), 1)
        self.assertIn("assessment", report)
        self.assertEqual(len(report["indicators_warnings"]), 1)

    def test_json_system_prompt_present(self) -> None:
        from report_schema import JSON_SYSTEM_PROMPT

        self.assertIn("JSON", JSON_SYSTEM_PROMPT)
        self.assertIn("key_findings", JSON_SYSTEM_PROMPT)

    def test_report_schema_spec(self) -> None:
        from report_schema import REPORT_SCHEMA, MANDATORY_FIELDS

        self.assertIn("key_findings", REPORT_SCHEMA["required"])
        self.assertIn("evidence_table", REPORT_SCHEMA["required"])
        self.assertIn("assessment", REPORT_SCHEMA["required"])
        self.assertEqual(
            MANDATORY_FIELDS, ("key_findings", "evidence_table", "assessment")
        )


# ---------------------------------------------------------------------------
# P1 integration — Orchestrator with blackboard
# ---------------------------------------------------------------------------


class TestOrchestratorBlackboardIntegration(unittest.IsolatedAsyncioTestCase):
    """Tests that the orchestrator correctly uses the blackboard when enabled."""

    def setUp(self) -> None:
        for mod in list(sys.modules):
            if mod in (
                "agent_orchestrator",
                "query_router",
                "chat_agentic",
                "agent_bus",
                "agent_blackboard",
                "conflict_detection",
                "config",
            ):
                del sys.modules[mod]

    class _ConfigStub:
        def __init__(
            self,
            enabled: bool = True,
            max_workers: int = 4,
            phase_timeout: float = 10.0,
            circuit_breaker_threshold: int = 3,
            circuit_breaker_window: int = 60,
            blackboard_enabled: bool = True,
        ):
            self.agent_orchestrator_enabled = enabled
            self.agent_orchestrator_max_workers = max_workers
            self.agent_orchestrator_phase_timeout = phase_timeout
            self.agent_orchestrator_circuit_breaker_threshold = (
                circuit_breaker_threshold
            )
            self.agent_orchestrator_circuit_breaker_window = circuit_breaker_window
            self.blackboard_enabled = blackboard_enabled

    def _patch_modules(
        self, route_block: str = "context", route_hits: list | None = None
    ) -> dict:
        from unittest.mock import AsyncMock, MagicMock

        route_hits = route_hits or []
        query_router = MagicMock()
        query_router.classify_query = MagicMock(return_value="vector")
        query_router.route_retrieval = AsyncMock(
            return_value={
                "route": "vector",
                "block": route_block,
                "hits": route_hits,
                "meta": {},
            }
        )
        query_router.VALID_ROUTES = ("vector", "graph", "spatial", "hybrid", "live")

        chat_agentic = MagicMock()
        chat_agentic.chat_agentic_enabled = MagicMock(return_value=True)
        chat_agentic.assess_coverage = MagicMock(
            return_value={
                "phase": "coverage",
                "char_count": len(route_block),
                "unique_sources": 1,
                "has_strong": True,
                "has_thin": False,
                "gaps": [],
                "needs_retrieve": False,
            }
        )
        chat_agentic.apply_corroboration_tags = MagicMock(
            return_value=(
                route_block,
                {
                    "phase": "corroboration",
                    "source_count": 1,
                    "corroborated": 0,
                    "uncorroborated": 0,
                    "tagged_lines": 0,
                },
            )
        )

        agent_bus = MagicMock()
        agent_bus.agent_bus_enabled = MagicMock(return_value=False)
        agent_bus.publish_action = AsyncMock(return_value={"ok": True, "delivered": 0})
        agent_bus.GLOBE_LAYER_KEYS = frozenset()
        agent_bus.AgentPublishBody = MagicMock()
        agent_bus.subscriber_count = MagicMock(return_value=0)

        return {
            "query_router": query_router,
            "chat_agentic": chat_agentic,
            "agent_bus": agent_bus,
        }

    async def test_blackboard_in_result_when_enabled(self) -> None:
        import agent_orchestrator
        import agent_blackboard

        modules = self._patch_modules(route_block="test context")
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
            return_value=self._ConfigStub(blackboard_enabled=True),
        ), patch.object(
            agent_blackboard,
            "get_config",
            return_value=self._ConfigStub(blackboard_enabled=True),
        ):
            result = await agent_orchestrator.orchestrate("test query")

        self.assertIn("blackboard", result)
        self.assertEqual(result["blackboard"]["query"], "test query")
        self.assertEqual(result["blackboard"]["evidence_count"], 0)

    async def test_no_blackboard_when_disabled(self) -> None:
        import agent_orchestrator
        import agent_blackboard

        modules = self._patch_modules(route_block="test context")
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
            return_value=self._ConfigStub(blackboard_enabled=False),
        ), patch.object(
            agent_blackboard,
            "get_config",
            return_value=self._ConfigStub(blackboard_enabled=False),
        ):
            result = await agent_orchestrator.orchestrate("test query")

        self.assertNotIn("blackboard", result)

    async def test_evidence_registered_from_hits(self) -> None:
        import agent_orchestrator
        import agent_blackboard

        hits = [
            {
                "text": "M4.5 earthquake near Bangkok",
                "source": "usgs",
                "url": "https://example.com",
            },
            {"text": "protest in downtown Bangkok", "source": "gdelt"},
        ]
        modules = self._patch_modules(route_block="context", route_hits=hits)
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
            return_value=self._ConfigStub(blackboard_enabled=True),
        ), patch.object(
            agent_blackboard,
            "get_config",
            return_value=self._ConfigStub(blackboard_enabled=True),
        ):
            result = await agent_orchestrator.orchestrate("Bangkok earthquake")

        self.assertEqual(result["blackboard"]["evidence_count"], 2)
        self.assertIn("[EVIDENCE-001]", result["blackboard"]["evidence_ids"])

    async def test_agent_status_includes_blackboard_flag(self) -> None:
        import agent_orchestrator
        import agent_blackboard

        modules = self._patch_modules()
        with patch.dict(
            sys.modules,
            {
                "agent_bus": modules["agent_bus"],
            },
        ), patch.object(
            agent_orchestrator,
            "get_config",
            return_value=self._ConfigStub(blackboard_enabled=True),
        ), patch.object(
            agent_blackboard,
            "get_config",
            return_value=self._ConfigStub(blackboard_enabled=True),
        ):
            status = await agent_orchestrator.agent_status()

        self.assertIn("blackboard_enabled", status)
        self.assertTrue(status["blackboard_enabled"])


if __name__ == "__main__":
    unittest.main()
