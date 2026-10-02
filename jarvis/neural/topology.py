"""Connectome topology: schema, validation, loading, synthetic generation.

HONESTY CONTRACT (read before using):

- No measured biological connectome ships with this repository.
- :data:`FLY_166K_SCHEMA` is *inspired by* Drosophila brain organization
  (region names and rough functional layout). Neuron counts, projections,
  weights and delays are schematic placeholders, NOT measured data.
- :class:`SyntheticGenerator` output is explicitly tagged
  ``"origin": "synthetic"`` and must never be presented as biological data.
- :func:`load_schema` / :func:`load_edges` accept real datasets when they
  become available; :func:`validate_edges` enforces the same invariants
  either way.

A schema describes *populations* (named neuron groups with LIF parameters)
and *projections* (statistical wiring rules between populations). Generating
a schema yields a concrete edge list that compiles into
:class:`~jarvis.neural.scale.SparseLIFNetwork`.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PopulationSpec:
    name: str
    count: int
    threshold: float = 1.0
    leak: float = 0.9
    refractory_steps: int = 0
    role: str = "sensory"  # sensory | association | motor | modulatory

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise ValueError("population needs a non-empty name")
        if self.count <= 0:
            raise ValueError(f"population {self.name}: count must be positive")
        if self.role not in ("sensory", "association", "motor", "modulatory"):
            raise ValueError(f"population {self.name}: unknown role {self.role!r}")


@dataclass
class ProjectionSpec:
    source: str
    target: str
    fan_out: int = 8
    weight_low: float = 0.1
    weight_high: float = 0.5
    delay_min: int = 1
    delay_max: int = 3
    recurrent: bool = False  # True: also wire within source population

    def __post_init__(self) -> None:
        if self.fan_out <= 0:
            raise ValueError("fan_out must be positive")
        if not (self.weight_low <= self.weight_high):
            raise ValueError("weight_low must be <= weight_high")
        if not (0 <= self.delay_min <= self.delay_max):
            raise ValueError("invalid delay range")


@dataclass
class ConnectomeSchema:
    name: str
    origin: str = "synthetic"  # synthetic | measured:<dataset>
    populations: list[PopulationSpec] = field(default_factory=list)
    projections: list[ProjectionSpec] = field(default_factory=list)

    def total_neurons(self) -> int:
        return sum(p.count for p in self.populations)

    def population_ranges(self) -> dict[str, tuple[int, int]]:
        ranges: dict[str, tuple[int, int]] = {}
        offset = 0
        for pop in self.populations:
            ranges[pop.name] = (offset, offset + pop.count)
            offset += pop.count
        return ranges

    def validate(self) -> list[str]:
        """Return a list of problems (empty == valid)."""
        problems: list[str] = []
        names = [p.name for p in self.populations]
        if len(set(names)) != len(names):
            problems.append("duplicate population names")
        for proj in self.projections:
            if proj.source not in names:
                problems.append(f"projection from unknown population {proj.source!r}")
            if proj.target not in names:
                problems.append(f"projection to unknown population {proj.target!r}")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "origin": self.origin,
            "populations": [vars(p) for p in self.populations],
            "projections": [vars(p) for p in self.projections],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConnectomeSchema":
        try:
            pops = [PopulationSpec(**p) for p in data.get("populations", [])]
            projs = [ProjectionSpec(**p) for p in data.get("projections", [])]
            schema = cls(name=str(data.get("name", "unnamed")),
                         origin=str(data.get("origin", "synthetic")),
                         populations=pops, projections=projs)
        except (TypeError, AttributeError) as exc:
            raise ValueError(f"invalid connectome schema: {exc}") from exc
        problems = schema.validate()
        if problems:
            raise ValueError(f"invalid connectome schema: {problems}")
        return schema


def load_schema(path: str) -> ConnectomeSchema:
    """Load a schema from a JSON file (synthetic or measured dataset)."""
    with open(path, "r", encoding="utf-8") as handle:
        return ConnectomeSchema.from_dict(json.load(handle))


def validate_edges(size: int, edges: list[tuple[int, int, float, int]],
                   max_delay: int) -> list[str]:
    """Check a concrete edge list against network bounds."""
    problems: list[str] = []
    seen: set[tuple[int, int]] = set()
    for i, (src, dst, w, d) in enumerate(edges):
        if not (0 <= src < size and 0 <= dst < size):
            problems.append(f"edge {i}: node out of range")
        if w != w or not isinstance(w, (int, float)):
            problems.append(f"edge {i}: invalid weight")
        if not (0 <= d <= max_delay):
            problems.append(f"edge {i}: delay out of range")
        if (src, dst) in seen:
            problems.append(f"edge {i}: duplicate edge ({src}->{dst})")
        seen.add((src, dst))
        if len(problems) > 25:
            problems.append("... truncated")
            break
    return problems


class SyntheticGenerator:
    """Deterministic synthetic topology generator (TESTING ONLY).

    Output edges are tagged synthetic via the schema's ``origin`` field.
    Two generators with the same seed produce identical edge lists.
    """

    def __init__(self, seed: int = 0) -> None:
        self.seed = int(seed)

    def generate(self, schema: ConnectomeSchema) -> list[tuple[int, int, float, int]]:
        problems = schema.validate()
        if problems:
            raise ValueError(f"cannot generate from invalid schema: {problems}")
        rng = random.Random(self.seed)
        ranges = schema.population_ranges()
        edges: list[tuple[int, int, float, int]] = []
        seen: set[tuple[int, int]] = set()
        for proj in schema.projections:
            src_lo, src_hi = ranges[proj.source]
            dst_lo, dst_hi = ranges[proj.target]
            for src in range(src_lo, src_hi):
                fan = min(proj.fan_out, dst_hi - dst_lo)
                targets = rng.sample(range(dst_lo, dst_hi), fan) if fan else []
                for dst in targets:
                    if (src, dst) in seen:
                        continue
                    seen.add((src, dst))
                    w = rng.uniform(proj.weight_low, proj.weight_high)
                    d = rng.randint(proj.delay_min, proj.delay_max)
                    edges.append((src, dst, w, d))
            if proj.recurrent:
                lo, hi = ranges[proj.source]
                for src in range(lo, hi):
                    dst = rng.randrange(lo, hi)
                    if dst == src or (src, dst) in seen:
                        continue
                    seen.add((src, dst))
                    edges.append((src, dst,
                                  rng.uniform(proj.weight_low, proj.weight_high),
                                  rng.randint(proj.delay_min, proj.delay_max)))
        edges.sort()
        return edges


# -- fly-inspired 166k schematic -------------------------------------------
# Region names follow Drosophila functional organization (optic lobe →
# central brain → descending/motor). Counts and wiring are SCHEMATIC
# placeholders summing to 166,000 — not measured data.

FLY_166K_SCHEMA = ConnectomeSchema(
    name="fly-166k-schematic-v1",
    origin="synthetic",
    populations=[
        PopulationSpec("lamina", 12000, threshold=0.8, leak=0.85, role="sensory"),
        PopulationSpec("medulla", 38000, threshold=1.0, leak=0.9, role="sensory"),
        PopulationSpec("lobula", 20000, threshold=1.0, leak=0.9, role="sensory"),
        PopulationSpec("antennal", 12000, threshold=0.8, leak=0.85, role="sensory"),
        PopulationSpec("gustatory", 3000, threshold=0.8, leak=0.85, role="sensory"),
        PopulationSpec("mushroom_body", 12000, threshold=1.2, leak=0.92, role="association"),
        PopulationSpec("central_complex", 10000, threshold=1.1, leak=0.9, role="association"),
        PopulationSpec("superior_protocerebrum", 30000, threshold=1.0, leak=0.9, role="association"),
        PopulationSpec("modulatory", 5000, threshold=1.4, leak=0.95, role="modulatory"),
        PopulationSpec("descending", 6000, threshold=1.0, leak=0.9, role="motor"),
        PopulationSpec("motor", 2000, threshold=0.9, leak=0.9, role="motor"),
        PopulationSpec("association_pool", 16000, threshold=1.0, leak=0.9, role="association"),
    ],
    projections=[
        ProjectionSpec("lamina", "medulla", fan_out=6, weight_low=0.2, weight_high=0.6),
        ProjectionSpec("medulla", "lobula", fan_out=6, weight_low=0.2, weight_high=0.6),
        ProjectionSpec("lobula", "superior_protocerebrum", fan_out=8, weight_low=0.15, weight_high=0.5),
        ProjectionSpec("lobula", "central_complex", fan_out=4, weight_low=0.15, weight_high=0.5),
        ProjectionSpec("antennal", "mushroom_body", fan_out=10, weight_low=0.1, weight_high=0.4),
        ProjectionSpec("antennal", "superior_protocerebrum", fan_out=6, weight_low=0.1, weight_high=0.4),
        ProjectionSpec("gustatory", "superior_protocerebrum", fan_out=6, weight_low=0.1, weight_high=0.4),
        ProjectionSpec("mushroom_body", "superior_protocerebrum", fan_out=6, weight_low=0.1, weight_high=0.45),
        ProjectionSpec("mushroom_body", "central_complex", fan_out=4, weight_low=0.1, weight_high=0.45),
        ProjectionSpec("central_complex", "descending", fan_out=8, weight_low=0.2, weight_high=0.6, recurrent=True),
        ProjectionSpec("superior_protocerebrum", "descending", fan_out=8, weight_low=0.15, weight_high=0.5),
        ProjectionSpec("descending", "motor", fan_out=10, weight_low=0.3, weight_high=0.8),
        ProjectionSpec("modulatory", "mushroom_body", fan_out=12, weight_low=0.05, weight_high=0.2, delay_min=2, delay_max=6),
        ProjectionSpec("modulatory", "central_complex", fan_out=12, weight_low=0.05, weight_high=0.2, delay_min=2, delay_max=6),
        ProjectionSpec("association_pool", "superior_protocerebrum", fan_out=6, weight_low=0.1, weight_high=0.4, recurrent=True),
        ProjectionSpec("superior_protocerebrum", "association_pool", fan_out=6, weight_low=0.1, weight_high=0.4),
    ],
)

assert FLY_166K_SCHEMA.total_neurons() == 166000, "fly schematic must total 166,000"
assert not FLY_166K_SCHEMA.validate(), "fly schematic must validate"


def build_network(schema: ConnectomeSchema, seed: int = 0,
                  max_delay: int = 32):
    """Generate + compile a SparseLIFNetwork from a schema (deterministic)."""
    from .scale import SparseLIFNetwork
    problems = schema.validate()
    if problems:
        raise ValueError(f"invalid schema: {problems}")
    net = SparseLIFNetwork(schema.total_neurons(), max_delay=max_delay)
    ranges = schema.population_ranges()
    for pop in schema.populations:
        lo, hi = ranges[pop.name]
        for i in range(lo, hi):
            net.thresholds[i] = pop.threshold
            net.leaks[i] = pop.leak
    net.refractory_steps = max(p.refractory_steps for p in schema.populations)
    edges = SyntheticGenerator(seed).generate(schema)
    edge_problems = validate_edges(net.size, edges, max_delay)
    if edge_problems:
        raise ValueError(f"generated edges invalid: {edge_problems[:5]}")
    net.connect_many(edges)
    net.compile()
    return net
