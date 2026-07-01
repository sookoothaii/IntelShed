"""Tests for API Contract Generation module."""

from __future__ import annotations

import unittest
from pathlib import Path

import sys

_backend = Path(__file__).resolve().parent
sys.path.insert(0, str(_backend))


class TestTSTypeGeneration(unittest.TestCase):
    """Test TypeScript type conversion."""

    def test_basic_types(self):
        import api_contracts

        self.assertEqual(api_contracts._ts_type({"type": "string"}), "string")
        self.assertEqual(api_contracts._ts_type({"type": "integer"}), "number")
        self.assertEqual(api_contracts._ts_type({"type": "number"}), "number")
        self.assertEqual(api_contracts._ts_type({"type": "boolean"}), "boolean")

    def test_array_type(self):
        import api_contracts

        result = api_contracts._ts_type({"type": "array", "items": {"type": "string"}})
        self.assertEqual(result, "string[]")

    def test_array_of_objects(self):
        import api_contracts

        result = api_contracts._ts_type(
            {
                "type": "array",
                "items": {"$ref": "#/components/schemas/Foo"},
            }
        )
        self.assertEqual(result, "Foo[]")

    def test_ref_type(self):
        import api_contracts

        result = api_contracts._ts_type({"$ref": "#/components/schemas/Bar"})
        self.assertEqual(result, "Bar")

    def test_object_type(self):
        import api_contracts

        result = api_contracts._ts_type(
            {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                },
                "required": ["id"],
            }
        )
        self.assertIn("id: number", result)
        self.assertIn("name?: string", result)

    def test_enum_type(self):
        import api_contracts

        result = api_contracts._ts_type({"enum": ["active", "inactive"]})
        self.assertEqual(result, '"active" | "inactive"')

    def test_none_schema(self):
        import api_contracts

        self.assertEqual(api_contracts._ts_type(None), "any")
        self.assertEqual(api_contracts._ts_type(None, "unknown"), "unknown")

    def test_empty_object(self):
        import api_contracts

        result = api_contracts._ts_type({"type": "object"})
        self.assertEqual(result, "Record<string, any>")


class TestPathToMethodName(unittest.TestCase):
    """Test path-to-method name conversion."""

    def test_simple_get(self):
        import api_contracts

        self.assertEqual(
            api_contracts._path_to_method_name("/api/health/ping", "get"),
            "getHealthPing",
        )

    def test_with_path_param(self):
        import api_contracts

        self.assertEqual(
            api_contracts._path_to_method_name("/api/ckan/{portal_id}/search", "get"),
            "getCkanPortalIdSearch",
        )

    def test_post(self):
        import api_contracts

        self.assertEqual(
            api_contracts._path_to_method_name("/api/ckan/harvest-all", "post"),
            "postCkanHarvestAll",
        )

    def test_delete(self):
        import api_contracts

        self.assertEqual(
            api_contracts._path_to_method_name("/api/items/{id}", "delete"),
            "deleteItemsId",
        )


class TestGenerateInterfaces(unittest.TestCase):
    """Test TypeScript interface generation."""

    def test_with_schemas(self):
        import api_contracts

        components = {
            "schemas": {
                "Dataset": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "count": {"type": "integer"},
                    },
                    "required": ["id", "title"],
                },
                "Status": {
                    "type": "string",
                    "enum": ["ok", "error"],
                },
            }
        }
        result = api_contracts._generate_interfaces(components)
        self.assertIn("export interface Dataset", result)
        self.assertIn("id: string", result)
        self.assertIn("title: string", result)
        self.assertIn("count?: number", result)
        self.assertIn("export type Status", result)

    def test_empty_components(self):
        import api_contracts

        result = api_contracts._generate_interfaces({})
        self.assertIn("No schema", result)

    def test_no_components(self):
        import api_contracts

        result = api_contracts._generate_interfaces(None)
        self.assertIn("No schema", result)


class TestGenerateEndpointFunctions(unittest.TestCase):
    """Test endpoint function generation."""

    def test_simple_get(self):
        import api_contracts

        paths = {
            "/api/health/ping": {
                "get": {
                    "summary": "Health ping",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"ok": {"type": "boolean"}},
                                    }
                                }
                            }
                        }
                    },
                }
            }
        }
        result = api_contracts._generate_endpoint_functions(
            paths, "http://127.0.0.1:8002"
        )
        self.assertIn("export async function getHealthPing", result)
        self.assertIn("BASE_URL", result)
        self.assertIn("apiFetch", result)

    def test_post_with_body(self):
        import api_contracts

        paths = {
            "/api/items": {
                "post": {
                    "summary": "Create item",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Item"}
                            }
                        }
                    },
                    "responses": {"201": {}},
                }
            }
        }
        result = api_contracts._generate_endpoint_functions(
            paths, "http://127.0.0.1:8002"
        )
        self.assertIn("export async function postItems", result)
        self.assertIn("body: Item", result)
        self.assertIn("JSON.stringify(body)", result)

    def test_get_with_path_param(self):
        import api_contracts

        paths = {
            "/api/items/{id}": {
                "get": {
                    "summary": "Get item by ID",
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {"200": {}},
                }
            }
        }
        result = api_contracts._generate_endpoint_functions(
            paths, "http://127.0.0.1:8002"
        )
        self.assertIn("export async function getItemsId", result)
        self.assertIn("id: string", result)
        self.assertIn("${id}", result)

    def test_get_with_query_params(self):
        import api_contracts

        paths = {
            "/api/search": {
                "get": {
                    "summary": "Search",
                    "parameters": [
                        {
                            "name": "q",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "integer"},
                        },
                    ],
                    "responses": {"200": {}},
                }
            }
        }
        result = api_contracts._generate_endpoint_functions(
            paths, "http://127.0.0.1:8002"
        )
        self.assertIn("export async function getSearch", result)
        self.assertIn("q?: string", result)
        self.assertIn("limit?: number", result)
        self.assertIn("URLSearchParams", result)


class TestGenerateTSClient(unittest.TestCase):
    """Test full TS client generation."""

    def test_generate_full_client(self):
        import api_contracts

        schema = {
            "openapi": "3.1.0",
            "info": {"title": "Test API", "version": "1.0.0"},
            "paths": {
                "/api/health": {
                    "get": {
                        "summary": "Health check",
                        "responses": {
                            "200": {
                                "content": {
                                    "application/json": {"schema": {"type": "object"}}
                                }
                            }
                        },
                    }
                }
            },
            "components": {
                "schemas": {
                    "Error": {
                        "type": "object",
                        "properties": {"detail": {"type": "string"}},
                        "required": ["detail"],
                    }
                }
            },
        }
        ts = api_contracts.generate_ts_client(schema)
        self.assertIn("AUTO-GENERATED", ts)
        self.assertIn("Test API", ts)
        self.assertIn("export interface Error", ts)
        self.assertIn("export async function getHealth", ts)
        self.assertIn("BASE_URL", ts)

    def test_generate_empty_paths(self):
        import api_contracts

        schema = {
            "openapi": "3.1.0",
            "info": {"title": "Empty", "version": "0.0.1"},
            "paths": {},
            "components": {},
        }
        ts = api_contracts.generate_ts_client(schema)
        self.assertIn("AUTO-GENERATED", ts)
        self.assertIn("BASE_URL", ts)


class TestAPIContractRouter(unittest.TestCase):
    """Test the FastAPI router endpoints."""

    def test_router_prefix(self):
        import api_contracts

        self.assertEqual(api_contracts.router.prefix, "/api/contracts")

    def test_router_tags(self):
        import api_contracts

        self.assertIn("api-contracts", api_contracts.router.tags)


if __name__ == "__main__":
    unittest.main()
