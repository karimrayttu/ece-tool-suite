from ece_suite.can_decode import decode_frames, parse_dbc, parse_log

DBC = """
BO_ 256 EngineData: 8 ECU
 SG_ RPM : 24|16@1+ (0.25,0) [0|16383.75] "rpm" ECU
 SG_ Temp : 40|8@1+ (1,-40) [-40|215] "degC" ECU
"""


def test_parse_and_decode_intel():
    msgs = parse_dbc(DBC)
    assert 256 in msgs and len(msgs[256].signals) == 2
    frames = parse_log("256 00 00 00 40 1F 5A 00 00")
    dec = decode_frames(msgs, frames)
    assert dec[0]["name"] == "EngineData"
    assert abs(dec[0]["signals"]["RPM"]["value"] - 2000.0) < 1e-6   # 0x1F40 * 0.25
    assert abs(dec[0]["signals"]["Temp"]["value"] - 50.0) < 1e-6    # 0x5A - 40


def test_signed_and_unknown_id():
    dec = decode_frames(parse_dbc(DBC), parse_log("999 0011"))
    assert dec[0]["name"] is None


def test_log_parsing_variants():
    frames = parse_log("0x100 DEADBEEF\n# comment\n256,0011")
    assert {f["id"] for f in frames} == {0x100}
