def select_axes(curve):
    """Prefer current and temperature, preserving source axis semantics."""
    varying = [a.name for a in curve.axes if len(a.values) > 1]
    priority = {"current": 0, "drain_current": 0, "junction_temperature": 1}
    varying.sort(key=lambda n: priority.get(n, 2))
    return tuple(varying[:2] or [curve.axes[0].name])
