"""Deterministic identity generation and recorded identity mappings.

The runtime is the sole allocator of application-authored identities in
production (``camera_agent.v2.identity.new_identity`` uses ``uuid4``). For
deterministic replay a test cannot rely on random UUIDs, so it substitutes a
deterministic identity factory or a recorded mapping. Both produce real
``UUID`` values that obey the same immutability and provenance contracts as
production identities, but are reproducible from a declared seed.

These controls only substitute the *source* of identity values. They never
allocate state revisions, author Ready, or alter provenance tokens; the runtime
still owns those once it lands.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterator, Mapping
from uuid import UUID, uuid5

#: The fixed namespace UUID used to derive deterministic test identities. It is
#: deliberately distinct from any production namespace so deterministic test
#: identities can never collide with a production ``uuid4`` stream.
IdentitySeed = UUID("a3f5b2c4-1a2e-4f7a-9b3c-0d1e2f3a4b5c")


def deterministic_session_salt() -> UUID:
    """Return a stable session salt for ``new_action_ordinal_uuid`` tests.

    Using this salt makes action-ordinal UUIDs reproducible across runs without
    binding tests to a live session's random salt.
    """
    return uuid5(IdentitySeed, "session-salt")


class DeterministicIdentityFactory:
    """Yield deterministic, monotonically numbered ``UUID`` values.

    Each call returns ``uuid5(seed, f"id:{n}")`` where ``n`` is a strictly
    increasing counter. Two factories with the same seed produce the same
    sequence; a factory with a different seed produces a disjoint sequence. The
    factory never reads randomness.
    """

    def __init__(self, seed: UUID = IdentitySeed) -> None:
        self._seed = seed
        self._counter = 0
        self._issued: list[UUID] = []

    def new_identity(self) -> UUID:
        """Return the next deterministic identity in this factory's sequence."""
        value = uuid5(self._seed, f"id:{self._counter}")
        self._counter += 1
        self._issued.append(value)
        return value

    def issued(self) -> tuple[UUID, ...]:
        """Return every identity this factory has issued, in issue order."""
        return tuple(self._issued)

    def __iter__(self) -> Iterator[UUID]:
        while True:
            yield self.new_identity()

    def reset(self) -> None:
        """Reset the counter so a fresh deterministic run reuses the same names."""
        self._counter = 0
        self._issued.clear()


class RecordedIdentityMap:
    """A recorded mapping from identity-kind to a fixed ``UUID``.

    Some scenarios need an explicit, replayable identity assignment (for
    example, to assert that a stale completion's task token differs from the
    current task). This map freezes a declared assignment and exposes the same
    ``is_current``-style lookup shape as a provenance token table, without
    authoring or mutating runtime state.
    """

    @dataclass(frozen=True, slots=True)
    class _Entry:
        kind: str
        identity: UUID

    def __init__(self) -> None:
        self._entries: dict[str, UUID] = {}

    def record(self, kind: str, identity: UUID) -> None:
        if not kind.strip():
            raise ValueError("identity kind must be nonempty")
        if kind in self._entries and self._entries[kind] != identity:
            raise ValueError(f"identity kind {kind!r} is already recorded")
        self._entries[kind] = identity

    def get(self, kind: str) -> UUID | None:
        return self._entries.get(kind)

    def require(self, kind: str) -> UUID:
        value = self._entries.get(kind)
        if value is None:
            raise KeyError(f"no recorded identity for kind {kind!r}")
        return value

    def as_token_table(self) -> Mapping[str, UUID]:
        """An immutable view of the recorded identities as a token table."""
        return MappingProxyType(dict(self._entries))

    def items(self) -> tuple[tuple[str, UUID], ...]:
        return tuple(sorted(self._entries.items()))
