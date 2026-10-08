import numpy as np
import pytest

from brickbuild.colours import Palette, parse_ldconfig, srgb_to_lab

SNIPPET = """\
0 // LDraw Solid Colours
0                              // LEGOID  26 - Black
0 !COLOUR Black            CODE   0   VALUE #1B2A34   EDGE #808080
0 !COLOUR Red              CODE   4   VALUE #B40000   EDGE #333333
0 !COLOUR Glow_Opaque      CODE  21   VALUE #E0FFB0   EDGE #B8FF4D   ALPHA 245   LUMINANCE 15
0 !COLOUR White            CODE  15   VALUE #F4F4F4   EDGE #333333
0 // LDraw Transparent Colours
0 !COLOUR Trans_Clear      CODE  47   VALUE #FCFCFC   EDGE #C3C3C3   ALPHA 128
0 // LDraw Chrome Plated Colours
0 !COLOUR Chrome_Gold      CODE 334   VALUE #DFC176   EDGE #C29D54   CHROME
0 // LDraw Glitter Colours
0 !COLOUR Glitter_Clear CODE 117 VALUE #FFFFFF EDGE #C3C3C3 ALPHA 128 MATERIAL GLITTER SIZE 1
0 // LDraw Internal Common Material Colours
0 !COLOUR Main_Colour      CODE  16   VALUE #FFFF80   EDGE #333333
"""


def test_lab_reference_values():
    # Reference values for sRGB under D65.
    np.testing.assert_allclose(srgb_to_lab([255, 255, 255]), [100, 0, 0], atol=0.01)
    np.testing.assert_allclose(srgb_to_lab([0, 0, 0]), [0, 0, 0], atol=0.01)
    np.testing.assert_allclose(srgb_to_lab([255, 0, 0]), [53.24, 80.09, 67.20], atol=0.05)
    np.testing.assert_allclose(srgb_to_lab([0, 0, 255]), [32.30, 79.19, -107.86], atol=0.05)


def test_parse_ldconfig_reads_values_and_materials():
    colours = {c.code: c for c in parse_ldconfig(SNIPPET)}
    assert set(colours) == {0, 4, 21, 15, 47, 334, 117, 16}
    assert colours[0].rgb == (0x1B, 0x2A, 0x34)
    assert colours[0].section == "Solid Colours"
    assert colours[47].alpha == 128
    assert colours[334].material == "CHROME"
    assert colours[117].material == "MATERIAL GLITTER"
    assert colours[21].luminance == 15


def test_palette_keeps_only_plain_solid_colours():
    colours = parse_ldconfig(SNIPPET)
    palette = Palette([c for c in colours if c.is_plain_solid])
    assert sorted(palette.codes.tolist()) == [0, 4, 15]


def test_nearest_snaps_in_lab():
    palette = Palette([c for c in parse_ldconfig(SNIPPET) if c.is_plain_solid])
    codes = palette.nearest([[0x1B, 0x2A, 0x34], [250, 10, 10], [255, 255, 255], [40, 40, 40]])
    assert codes.tolist() == [0, 4, 15, 0]


def test_empty_palette_is_an_error():
    with pytest.raises(ValueError):
        Palette([])


def test_real_ldconfig_palette(library):
    palette = Palette.from_ldconfig(library.ldconfig_path)
    for code in (0, 1, 2, 4, 14, 15, 19, 25, 70, 71, 72):
        assert code in palette, code
    for code in (16, 24, 47, 334):  # internal, transparent, chrome
        assert code not in palette, code
    assert 50 <= len(palette) <= 200
    # Every palette colour snaps to itself.
    rgb = np.array([c.rgb for c in palette.colours])
    assert palette.nearest(rgb).tolist() == palette.codes.tolist()
