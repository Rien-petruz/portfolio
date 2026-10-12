"""The split-process simulator relies on worlds with a shared epoch evolving identically."""

from marketintel.sim.world import MarketWorld


def test_grid_worlds_with_same_seed_and_epoch_match_regardless_of_call_times():
    a = MarketWorld(5, synthetic_assets=20, grid_epoch=100.0)
    b = MarketWorld(5, synthetic_assets=20, grid_epoch=100.0)
    a.dislocation_rate_per_min = b.dislocation_rate_per_min = 600.0
    for t in (100.013, 100.5, 101.0, 102.337, 103.0):
        a.advance_to_wall(t)
    for t in (100.2, 103.0):
        b.advance_to_wall(t)
    assert a.t == b.t and a.values == b.values
    assert [(d.asset, d.venue, d.bps) for d in a.dislocations] == [(d.asset, d.venue, d.bps) for d in b.dislocations]


def test_grid_world_never_steps_backwards():
    w = MarketWorld(1, grid_epoch=0.0)
    w.advance_to_wall(1.0)
    t = w.t
    assert w.advance_to_wall(0.5) == 0.0 and w.t == t
