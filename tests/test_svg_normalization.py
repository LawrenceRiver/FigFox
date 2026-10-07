import xml.etree.ElementTree as ET

import pytest

from figfox_plus.native.document import parse


def test_bare_ampersands_preserve_text_attributes_and_existing_entities():
    repairs = []
    root = parse('<svg xmlns="http://www.w3.org/2000/svg"><desc>Tempo & Key &amp; Mood</desc>'
                 '<text id="t" aria-label="A & B">R&amp;D &#38; Sound</text></svg>', repairs=repairs)
    assert root[0].text == 'Tempo & Key & Mood'
    assert root[1].text == 'R&D & Sound'
    assert root[1].get('aria-label') == 'A & B'
    assert repairs == [{'kind': 'escape_bare_ampersand', 'count': 2}]


def test_literal_ampersands_in_cdata_and_comments_are_not_normalized():
    repairs = []
    root = parse('<svg><!-- A & B --><?note A & B?><desc><![CDATA[A & B]]></desc>'
                 '<text>C & D</text></svg>', repairs=repairs)
    assert root[0].text == 'A & B'
    assert root[1].text == 'C & D'
    assert repairs[0]['count'] == 1


@pytest.mark.parametrize('source', [
    '<svg><text>A & B</svg>',
    '<svg><text>&unknown;</text></svg>',
    '<svg><text>A & B &#0;</text></svg>',
])
def test_other_xml_errors_still_fail(source):
    with pytest.raises(ET.ParseError):
        parse(source)


def test_valid_svg_is_not_repaired():
    repairs = []
    root = parse('<svg><desc>A &amp; B</desc><rect id="r" x="12" width="20"/></svg>', repairs=repairs)
    assert root[1].attrib == {'id': 'r', 'x': '12', 'width': '20'}
    assert repairs == []
