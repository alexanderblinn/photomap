from src.geo_utils import dms_to_decimal


def test_dms_to_decimal():
    # 51° 30' 26" N should be approx 51.5072 (London)
    dms = [(51, 1), (30, 1), (26, 1)]
    assert abs(dms_to_decimal(dms, "N") - 51.5072) < 0.01
