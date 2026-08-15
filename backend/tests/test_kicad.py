from ece_suite.kicad_analyze import analyze_text

FIXTURE = """
(kicad_sch (version 20240130)
  (symbol (lib_id "Regulator_Linear:AMS1117-3.3") (at 100 100 0)
    (property "Reference" "U1" (at 0 0 0))
    (property "Value" "AMS1117-3.3" (at 0 0 0))
    (property "Footprint" "Package_TO_SOT_SMD:SOT-223" (at 0 0 0)))
  (symbol (lib_id "Device:R") (at 50 50 0)
    (property "Reference" "R1" (at 0 0 0))
    (property "Value" "10k" (at 0 0 0)))
  (symbol (lib_id "Device:C") (at 60 60 0)
    (property "Reference" "C1" (at 0 0 0))
    (property "Value" "100nF" (at 0 0 0)))
  (symbol (lib_id "power:GND") (at 0 0 0)
    (property "Reference" "#PWR01" (at 0 0 0))
    (property "Value" "GND" (at 0 0 0)))
  (label "SDA" (at 10 10 0))
  (global_label "VCC" (at 20 20 0))
)
"""


def test_analyze_extracts_components_and_detectors():
    r = analyze_text(FIXTURE)
    assert r["component_count"] == 3  # U1, R1, C1 (power symbol skipped)
    assert {c["ref"] for c in r["components"]} == {"U1", "R1", "C1"}
    assert r["detectors"]["regulators"] == ["U1"]
    assert r["detectors"]["decoupling_caps"] == 1
    assert r["detectors"]["resistors"] == 1
    assert "SDA" in r["nets"] and "VCC" in r["nets"]
