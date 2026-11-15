"""Changing the layout's coordinate origin must preserve a router recommendation."""
import copy

import pytest

from advisor.advise import advise
from advisor.tests.test_advise import DESK, DESK_T1, NODES, T1, desk_links, desk_xray, links, obj, xray


@pytest.mark.parametrize('desk',[False,True])
@pytest.mark.parametrize('offset',[(3.25,-2.4),(-4.5,6.125)])
def test_advice_geometry_follows_translated_layout_and_grid(desk,offset):
    nodes,point = (DESK,DESK_T1) if desk else (NODES,T1)
    grid = desk_xray([(*point,9)]) if desk else xray([(*point,9)])
    readings = desk_links() if desk else links()
    objects = [obj(*point)]
    expected = advise(grid,readings,nodes,objects)
    assert expected is not None
    moved_nodes,moved_grid,moved_objects = copy.deepcopy((nodes,grid,objects))
    for collection in ('nodes','router_spots'):
        for item in moved_nodes[collection]:
            item['xyz_m'][:2] = [v+d for v,d in zip(item['xyz_m'][:2],offset)]
    moved_grid['origin_m'] = [v+d for v,d in zip(grid['origin_m'],offset)]
    moved_objects[0]['xy_m'] = [v+d for v,d in zip(point,offset)]
    result = advise(moved_grid,readings,moved_nodes,moved_objects)
    assert result is not None
    assert result['xy_m'] == pytest.approx([round(v+d,2) for v,d in zip(point,offset)])
    for field in ('id','near','link','to_spot','move_m','dist_change_m','why','text'):
        assert result[field] == expected[field]
