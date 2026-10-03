from collectors.ocr import parse_row, is_valid_mac


def test_valid_and_invalid_mac():
    assert is_valid_mac("aa:bb:cc:dd:ee:ff")
    assert not is_valid_mac("aa:bb:cc:dd:ee")


def test_parse_row_ok():
    r = parse_row("aa:bb:cc:dd:ee:ff 100 200 54.0 no 3600")
    assert r["mac"] == "aa:bb:cc:dd:ee:ff"
    assert r["tx_packet"] == 100 and r["rx_packet"] == 200
    assert r["power_saving"] == "no"


def test_header_and_short_lines_ignored():
    assert parse_row("MAC Address Tx Rx") is None
    assert parse_row("aa:bb:cc:dd:ee:ff 1") is None
    assert parse_row("") is None
