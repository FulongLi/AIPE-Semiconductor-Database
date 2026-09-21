from aipe_devices.domain.base import Model
from aipe_devices.domain.provenance import Dependency
from aipe_devices.schema.enums import Freshness


class DerivedNode(Model):
    id: str
    version: str
    dependencies: tuple[Dependency, ...]
    freshness: Freshness = Freshness.CURRENT


def invalidate(nodes: tuple[DerivedNode, ...], changed_ids: set[str]) -> tuple[DerivedNode, ...]:
    """Caller supplies changed input/recipe IDs; mark transitive dependants stale."""
    stale = set(changed_ids) | {n.id for n in nodes if n.freshness == Freshness.STALE}
    while True:
        expanded = stale | {n.id for n in nodes if any(d.id in stale for d in n.dependencies)}
        if expanded == stale:
            break
        stale = expanded
    return tuple(
        n.model_copy(update={"freshness": Freshness.STALE}) if n.id in stale else n for n in nodes
    )
