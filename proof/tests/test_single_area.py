"""Synthetic layouts exercise one sensing area without a fabricated zone split."""
import pytest

from proof import layout
from proof.score import threshold_zone
from proof.walk import script


def single_area():
    return {"frame":{"strip_m":[2,1],"size_m":[2,2]},
            "zones":[{"id":7,"name":"Sensing area","centre_m":[1,0.5]}],
            "nodes":[{"id":"a","xyz_m":[1,-0.5,1]},{"id":"b","xyz_m":[1,1.5,1]}],
            "links":[{"id":"sense","tx":"a","rx":"b"},
                     {"id":"disabled","tx":"b","rx":"a","classifier":False}]}


@pytest.mark.parametrize('point,inside',[((0,0),True),((2,0.5),True),((1,0.5),True),((2,1),False),
                                       ((-0.01,0),False),((2.01,0),False),((1,1.01),False)])
def test_single_zone_uses_its_actual_id_and_the_strips_bounds(point,inside):
    assert layout.zone_at(single_area(),*point) == (7 if inside else 0)


def test_baseline_uses_enabled_crossing_link_without_a_split():
    doc = single_area()
    assert layout.link_zones(doc) == {'sense':7}
    readings = {'sense':{'drop_db':2},'disabled':{'drop_db':20}}
    assert threshold_zone(readings,doc=doc) == 0
    readings['sense']['drop_db'] = 4
    assert threshold_zone(readings,doc=doc) == 7
    doc['links'][0]['classifier'] = False
    assert threshold_zone(readings,doc=doc) is None


def test_one_area_walk_steps_on_and_off_the_spot_and_has_no_middle_mark():
    steps = script('train',single_area())
    visits = [text for text,_,_,_ in steps if text.startswith('Stand still on the spot')]
    assert len(visits) == 3
    assert not any('middle mark' in text for text,_,_,_ in steps)
