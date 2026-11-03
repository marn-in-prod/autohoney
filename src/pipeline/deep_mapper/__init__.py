"""Deep mapper module — detailed investigation of candidate targets."""

from pipeline.deep_mapper.models import (
    CodeTraceEntry,
    SchemerMotivation,
    ConfigurationPattern,
    LegitimateChange,
    CodebaseConventions,
    ModificationSurface,
    DeepMapping,
    FailedTarget,
    DeepMapResult,
)
from pipeline.deep_mapper.mapper import deep_map_targets, write_deep_map_yaml, read_deep_map_yaml

__all__ = [
    "CodeTraceEntry",
    "SchemerMotivation",
    "ConfigurationPattern",
    "LegitimateChange",
    "CodebaseConventions",
    "ModificationSurface",
    "DeepMapping",
    "FailedTarget",
    "DeepMapResult",
    "deep_map_targets",
    "write_deep_map_yaml",
    "read_deep_map_yaml",
]
