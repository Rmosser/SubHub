from io import BytesIO

import qrcode

from app.services.qr_decoder import decode_qr_url


def test_decode_qr_url_with_declared_runtime_decoder() -> None:
    expected = "https://example.test/subscription?token=clean-install"
    image = qrcode.make(expected)
    output = BytesIO()
    image.save(output, format="PNG")

    assert decode_qr_url(output.getvalue()) == expected
