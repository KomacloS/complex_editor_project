from complex_editor.domain.pinxml import MacroInstance, PinXML


def test_roundtrip():
    given = [MacroInstance("DIODE", {"Current": "50e-e", "Value": 0.2})]
    xml = PinXML.serialize(given)
    got = PinXML.deserialize(xml)
    assert got == given


def test_omit_default_params():
    inst = MacroInstance("CAPACITOR", {"MeasureMode": "Default", "Frequency": 10})
    xml = PinXML.serialize([inst])
    txt = xml.decode("utf-16")
    assert "MeasureMode" not in txt
    assert "Frequency" in txt
