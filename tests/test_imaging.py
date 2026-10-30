import pytest
from PIL import Image, ImageCms

from helpers import encode, page_image
from mangareader.imaging import ImageDecodeError, decode, read_size, resize_lanczos


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP", "AVIF", "JXL", "BMP", "GIF", "TIFF"])
def test_decode_all_formats(fmt):
    d = decode(encode(page_image(1, (300, 400)), fmt))
    assert d.format == fmt and d.image.size == (300, 400) and d.image.mode in {"L", "LA", "RGB", "RGBA"}


def test_jpeg_tables_kept():
    d = decode(encode(page_image(1), "JPEG", quality=88))
    assert d.jpeg.qtables and d.jpeg.subsampling in (0, 1, 2)


def test_icc_kept():
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    assert decode(encode(page_image(1), "PNG", icc_profile=icc)).icc == icc


@pytest.mark.parametrize("mode,expected", [("P", "RGB"), ("1", "L"), ("I;16", "L"), ("CMYK", "RGB")])
def test_modes_normalized(mode, expected):
    fmt = "JPEG" if mode == "CMYK" else ("TIFF" if mode == "I;16" else "PNG")
    d = decode(encode(page_image(1).convert(mode), fmt))
    assert d.image.mode == expected
    if mode == "CMYK":
        assert d.icc is None


def test_palette_with_transparency_becomes_rgba():
    img = page_image(1).convert("P")
    assert decode(encode(img, "PNG", transparency=0)).image.mode == "RGBA"


def test_huge_image_is_not_a_bomb():  # Review Focus 1
    d = decode(encode(Image.new("L", (12000, 10000), 200), "PNG"))
    assert d.image.size == (12000, 10000)


def test_garbage_raises():
    with pytest.raises(ImageDecodeError):
        decode(b"not an image")


def test_truncated_raises():
    with pytest.raises(ImageDecodeError):
        decode(encode(page_image(1), "PNG")[:500])


def test_read_size_from_head():
    data = encode(page_image(1, (1234, 2345)), "JPEG")
    assert read_size(data[:65536]) == (1234, 2345) and read_size(b"xx") is None


def test_draft_reduces_jpeg():
    d = decode(encode(page_image(1, (2000, 3000)), "JPEG"), draft=(240, 360))
    assert 240 <= d.image.width < 2000


def test_resize_lanczos():
    assert resize_lanczos(page_image(1, (1000, 1500)), 200, 300).size == (200, 300)
