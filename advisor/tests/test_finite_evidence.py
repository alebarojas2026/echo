import pytest

from advisor.advise import advise
from advisor.tests.test_advise import NODES, T1, links, obj, xray


@pytest.mark.parametrize("drop", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_wifi_drop_is_not_evidence_of_current_blockage(drop):
    assert advise(xray([(*T1, 9)]), links(pi5_unoq_wifi=drop), NODES, [obj(*T1)]) is None


@pytest.mark.parametrize("age", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_age_does_not_prove_object_persistence(age):
    assert advise(xray([(*T1, 9)]), links(), NODES, [obj(*T1, since=age)]) is None


@pytest.mark.parametrize("drop", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_secondary_link_is_not_explanatory_evidence(drop):
    result = advise(xray([(*T1, 9)]), links(east_pi5_ble=drop), NODES, [obj(*T1)])
    assert result is not None
    assert "east>pi5:ble" not in result["why"]


def test_valid_thresholds_still_trigger_advice():
    result = advise(xray([(*T1, 9)]), links(pi5_unoq_wifi=3, east_pi5_ble=3), NODES, [obj(*T1, since=5)])
    assert result is not None and "east>pi5:ble" in result["why"]
