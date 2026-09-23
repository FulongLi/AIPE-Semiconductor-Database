from itertools import product

from aipe_devices.domain.curves import Curve

from .spec import TensorView


def slice_tensor(curve: Curve, axes: tuple[str, ...], fixed: dict[str, float]) -> TensorView:
    """Exact named coordinates; axes may be reordered. Interpolation is not implicit."""
    by_name = {a.name: a for a in curve.axes}
    if len(set(axes)) != len(axes) or not set(axes) <= by_name.keys():
        raise ValueError("Requested axes must be distinct source axes")
    if set(fixed) != by_name.keys() - set(axes):
        raise ValueError("Every remaining axis requires one explicit fixed coordinate")
    if any(len(set(a.values)) != len(a.values) for a in curve.axes):
        raise ValueError("Duplicate source coordinates are ambiguous for slicing")
    indices = {}
    for name, value in fixed.items():
        try:
            indices[name] = by_name[name].values.index(value)
        except ValueError as exc:
            raise ValueError(
                f"{name}={value} is not an exact source point; no interpolation"
            ) from exc
    selected_axes = tuple(by_name[n] for n in axes)
    values = []
    for selected in product(*(range(len(a.values)) for a in selected_axes)):
        coordinate = indices | dict(zip(axes, selected))
        offset = 0
        for axis in curve.axes:
            offset = offset * len(axis.values) + coordinate[axis.name]
        values.append(curve.values[offset])
    return TensorView(axes=selected_axes, values=tuple(values))
