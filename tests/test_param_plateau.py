from analysis.param_plateau import default_neighbours, is_plateau, plateau_table

DEFAULT = (252, 8)


def _scores(default_value: float, neighbour_value: float) -> dict[tuple[int, int], float]:
    grid = {(lb, n): neighbour_value for lb in (63, 126, 189, 252) for n in (4, 6, 8, 10)}
    grid[DEFAULT] = default_value
    return grid


def test_table_shape_and_neighbours_of_default():
    table = plateau_table(_scores(0.8, 0.75))
    assert list(table.index) == [63, 126, 189, 252]
    assert list(table.columns) == [4, 6, 8, 10]
    nb = default_neighbours(table, DEFAULT)
    assert set(nb) == {(189, 8), (252, 6), (252, 10)}  # no lookback above 252 in the grid


def test_plateau_when_neighbours_close_and_spike_when_not():
    assert is_plateau(plateau_table(_scores(0.80, 0.75)), DEFAULT)
    assert not is_plateau(plateau_table(_scores(0.80, 0.50)), DEFAULT)
