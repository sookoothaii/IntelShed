"""OpenTelemetry tracing setup (I4).

Auto-instruments FastAPI routes when opentelemetry packages are installed
and OTEL_EXPORTER_OTLP_ENDPOINT is set. Zero overhead when disabled.
"""

from __future__ import annotations

import os


def otel_enabled() -> bool:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    return bool(endpoint) and os.getenv("WORLDBASE_OTEL", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def setup_otel(app) -> bool:
    """Instrument FastAPI app with OpenTelemetry. Returns True if enabled.

    Requires: pip install opentelemetry-instrumentation-fastapi opentelemetry-exporter-otlp
    """
    if not otel_enabled():
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        service_name = os.getenv("OTEL_SERVICE_NAME", "worldbase-api")
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        FastAPIInstrumentor.instrument_app(app)
        return True
    except ImportError:
        return False
    except Exception:
        return False
