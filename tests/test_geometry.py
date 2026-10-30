from helpers import encode, make_zip, page_image
from mangareader.export.geometry import Placed, crops_for_selection, output_size, stitch
from mangareader.export.model import load_page_image
from mangareader.sources import open_source


def test_single_page_crop_is_pixel_exact():
    img = page_image(3, (1000, 1500))
    placed = [Placed(0, 0, 0, 500, 750, 1000, 1500)]   # масштаб 0.5
    crops = crops_for_selection(placed, (100, 100, 200, 300))
    assert crops[0].box == (200, 200, 600, 800)
    assert output_size(placed, crops) == (400, 600)
    assert stitch(placed, crops, {0: img}).tobytes() == img.crop((200, 200, 600, 800)).tobytes()


def test_spread_upscales_smaller_page_to_larger():
    a, b = page_image(1, (1000, 1500)), page_image(2, (500, 750))
    placed = [Placed(0, 0, 0, 1000, 1500, 1000, 1500), Placed(1, 1000, 0, 1000, 1500, 500, 750)]
    crops = crops_for_selection(placed, (900, 0, 200, 1500))
    out = stitch(placed, crops, {0: a, 1: b})
    assert out.size == output_size(placed, crops) == (200, 1500)
    assert out.crop((0, 0, 100, 1500)).tobytes() == a.crop((900, 0, 1000, 1500)).tobytes()


def test_ribbon_vertical_stitch_and_modes():
    a, b = page_image(1, (800, 1000)).convert("L"), page_image(2, (800, 1000)).convert("RGBA")
    placed = [Placed(0, 0, 0, 800, 1000, 800, 1000), Placed(1, 0, 1000, 800, 1000, 800, 1000)]
    out = stitch(placed, crops_for_selection(placed, (0, 900, 800, 200)), {0: a, 1: b})
    assert out.size == (800, 200) and out.mode == "RGBA"


def test_selection_outside_pages_is_clamped():
    placed = [Placed(0, 0, 0, 100, 100, 100, 100)]
    assert crops_for_selection(placed, (-50, -50, 80, 80))[0].box == (0, 0, 30, 30)
    assert crops_for_selection(placed, (200, 200, 10, 10)) == []


def test_load_page_image(tmp_path, ctx):
    data = encode(page_image(1), "JPEG")
    src = open_source(make_zip(tmp_path / "a.cbz", {"1.jpg": data}), ctx)
    page = load_page_image(src, 0)
    assert page.original.data == data and page.decoded.format == "JPEG"
