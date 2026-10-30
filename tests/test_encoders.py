from io import BytesIO

import pymupdf
import pytest
from PIL import Image, ImageCms, JpegImagePlugin

from helpers import encode, page_image
from mangareader.export.encoders import (QUALITY_PRESETS, EncodeOptions, Encoded, OutFormat, Resize, apply_resize,
                                         encode_fragment, encode_page)
from mangareader.export.model import PageImage
from mangareader.imaging import decode
from mangareader.sources.base import Original

EXTS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif"}


def pi(fmt, mode="RGB", **kw):
    data = encode(page_image(1, (400, 600)).convert(mode), fmt, **kw)
    return PageImage(decode(data), Original(data, EXTS[fmt]))


def test_presets_match_spec():
    assert QUALITY_PRESETS["max"] == {OutFormat.JPEG: 100, OutFormat.WEBP: 100, OutFormat.AVIF: 95}
    assert QUALITY_PRESETS["high"] == {OutFormat.JPEG: 92, OutFormat.WEBP: 90, OutFormat.AVIF: 80}
    assert QUALITY_PRESETS["medium"] == {OutFormat.JPEG: 85, OutFormat.WEBP: 80, OutFormat.AVIF: 65}
    assert QUALITY_PRESETS["compact"] == {OutFormat.JPEG: 75, OutFormat.WEBP: 70, OutFormat.AVIF: 50}


def test_original_whole_page_is_byte_copy():
    p = pi("JPEG")
    assert encode_page(p, EncodeOptions(OutFormat.ORIGINAL)) == Encoded(p.original.data, ".jpg")


def test_original_with_resize_reencodes_same_format():
    p = pi("PNG")
    enc = encode_page(p, EncodeOptions(OutFormat.ORIGINAL, resize=Resize("percent", 50)))
    assert enc.ext == ".png" and Image.open(BytesIO(enc.data)).size == (200, 300)


@pytest.mark.parametrize("fmt,ext,check", [
    ("PNG", ".png", "lossless"), ("WEBP", ".webp", "lossless"), ("GIF", ".png", "lossless"), ("JPEG", ".jpg", "jpeg")])
def test_original_fragment_rules(fmt, ext, check):
    p = pi(fmt)
    frag = p.decoded.image.crop((10, 10, 200, 300))
    enc = encode_fragment(frag, [p], EncodeOptions(OutFormat.ORIGINAL))
    back = Image.open(BytesIO(enc.data))
    assert enc.ext == ext
    if check == "lossless":
        assert back.convert("RGB").tobytes() == frag.convert("RGB").tobytes()
    else:
        assert back.quantization == p.decoded.jpeg.qtables


def test_rendered_document_fragment_is_png():
    p = PageImage(decode(encode(page_image(1), "PNG")), None)
    p.decoded.format = None
    assert encode_fragment(p.decoded.image, [p], EncodeOptions(OutFormat.ORIGINAL)).ext == ".png"


def test_mixed_sources_fragment_is_png():
    enc = encode_fragment(page_image(1), [pi("JPEG"), pi("PNG")], EncodeOptions(OutFormat.ORIGINAL))
    assert enc.ext == ".png"


def test_jpeg_quality_subsampling_and_flatten():
    rgba = PageImage(decode(encode(page_image(1).convert("RGBA"), "PNG")), None)
    hi = Image.open(BytesIO(encode_page(rgba, EncodeOptions(OutFormat.JPEG, 92)).data))
    lo = Image.open(BytesIO(encode_page(rgba, EncodeOptions(OutFormat.JPEG, 75)).data))
    assert hi.mode == "RGB" and JpegImagePlugin.get_sampling(hi) == 0 and JpegImagePlugin.get_sampling(lo) == 2


def test_grayscale_and_icc_kept():
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    g = PageImage(decode(encode(page_image(1).convert("L"), "PNG", icc_profile=icc)), None)
    out = Image.open(BytesIO(encode_page(g, EncodeOptions(OutFormat.PNG)).data))
    assert out.mode == "L" and out.info.get("icc_profile") == icc


@pytest.mark.parametrize("fmt,ext", [(OutFormat.WEBP, ".webp"), (OutFormat.AVIF, ".avif"), (OutFormat.TIFF, ".tif"),
                                     (OutFormat.BMP, ".bmp"), (OutFormat.PNG, ".png"), (OutFormat.JPEG, ".jpg")])
def test_formats_reopen(fmt, ext):
    enc = encode_page(pi("PNG"), EncodeOptions(fmt, 80))
    assert enc.ext == ext and Image.open(BytesIO(enc.data)).size == (400, 600)


def test_resize_never_upscales():
    img = page_image(1, (400, 600))
    assert apply_resize(img, Resize("percent", 50)).size == (200, 300)
    assert apply_resize(img, Resize("long_side", 300)).size == (200, 300)
    assert apply_resize(img, Resize("long_side", 5000)).size == (400, 600)
    assert apply_resize(img, Resize()).size == (400, 600)


def test_pdf_embeds_original_jpeg():
    p = pi("JPEG")
    enc = encode_page(p, EncodeOptions(OutFormat.PDF))
    doc = pymupdf.open(stream=enc.data)
    assert enc.ext == ".pdf" and doc.extract_image(doc[0].get_images()[0][0])["image"] == p.original.data
    assert round(doc[0].rect.width) == round(400 * 72 / 300)


def test_pdf_from_webp_page_is_lossless_png():
    p = pi("WEBP", lossless=True)
    doc = pymupdf.open(stream=encode_page(p, EncodeOptions(OutFormat.PDF)).data)
    assert doc.extract_image(doc[0].get_images()[0][0])["ext"] == "png"
