"""Resolve competing candidates into one value per field, with confidence and reasoning.

Scoring: candidates are grouped by normalized value. Each candidate contributes
`reliability(source) * confidence * recency_decay`, and a group's score is the
probability that at least one supporting observation is right:

    score = 1 - prod(1 - contribution_i)

Independent sources agreeing therefore raise confidence, while one weak source
cannot outvote a strong one.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.domain.models import Candidate, FieldName, ResolvedField
from app.domain.normalize import normalize


@dataclass(frozen=True)
class ResolverConfig:
    source_reliability: dict[str, float] = field(default_factory=dict)
    default_reliability: float = 0.6
    half_life_days: float = 180.0
    conflict_margin: float = 0.15
    conflict_penalty: float = 0.2


@dataclass
class _Group:
    display_value: str
    score_complement: float = 1.0
    sources: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        return 1.0 - self.score_complement


class FieldResolver:
    def __init__(self, config: ResolverConfig | None = None, now: datetime | None = None):
        self.config = config or ResolverConfig()
        self._now = now

    def _decay(self, observed_at: datetime) -> float:
        now = self._now or datetime.now(UTC)
        age_days = max((now - observed_at).total_seconds() / 86400, 0.0)
        return 0.5 ** (age_days / self.config.half_life_days)

    def _contribution(self, c: Candidate) -> float:
        reliability = self.config.source_reliability.get(
            c.source, self.config.default_reliability
        )
        return reliability * c.confidence * self._decay(c.observed_at)

    def resolve_field(self, name: FieldName, candidates: list[Candidate]) -> ResolvedField | None:
        relevant = [c for c in candidates if c.field == name and c.value.strip()]
        if not relevant:
            return None

        groups: dict[str, _Group] = {}
        for c in sorted(relevant, key=lambda c: c.observed_at, reverse=True):
            key = normalize(name, c.value)
            group = groups.setdefault(key, _Group(display_value=c.value.strip()))
            group.score_complement *= 1.0 - self._contribution(c)
            if c.source not in group.sources:
                group.sources.append(c.source)

        ranked = sorted(groups.values(), key=lambda g: g.score, reverse=True)
        winner = ranked[0]
        runner_up = ranked[1] if len(ranked) > 1 else None

        confidence = winner.score
        conflict = bool(
            runner_up and winner.score - runner_up.score < self.config.conflict_margin
        )
        if conflict:
            confidence *= 1.0 - self.config.conflict_penalty

        return ResolvedField(
            field=name,
            value=winner.display_value,
            confidence=round(confidence, 4),
            conflict=conflict,
            sources=winner.sources,
            reasoning=self._explain(winner, runner_up, conflict),
        )

    def resolve(self, candidates: list[Candidate]) -> dict[FieldName, ResolvedField]:
        by_field: dict[FieldName, list[Candidate]] = defaultdict(list)
        for c in candidates:
            by_field[c.field].append(c)
        resolved = {}
        for name, items in by_field.items():
            result = self.resolve_field(name, items)
            if result:
                resolved[name] = result
        return resolved

    @staticmethod
    def _explain(winner: _Group, runner_up: _Group | None, conflict: bool) -> str:
        parts = [
            f"'{winner.display_value}' supported by {len(winner.sources)} source(s) "
            f"({', '.join(winner.sources)}), score {winner.score:.2f}."
        ]
        if runner_up:
            parts.append(
                f"Runner-up '{runner_up.display_value}' from {', '.join(runner_up.sources)} "
                f"scored {runner_up.score:.2f}."
            )
        if conflict:
            parts.append("Scores are close; flagged as conflict and confidence reduced.")
        return " ".join(parts)
