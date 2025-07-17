from complex_editor.domain.pinxml import MacroInstance, PinXML


def test_roundtrip():
    given = [MacroInstance("DIODE", {"Current": "50e-e", "Value": 0.2})]
    xml = PinXML.serialize(given)
    got = PinXML.deserialize(xml)
    assert got == given
