from msmail.core import render


def test_unwrap_safelink_returns_original_url():
    wrapped = (
        "https://nam12.safelinks.protection.outlook.com/"
        "?url=https%3A%2F%2Fexample.com%2Fa%3Fx%3D1"
    )

    assert render.unwrap_safelink(wrapped) == "https://example.com/a?x=1"


def test_html_to_text_removes_noise_and_keeps_links():
    text = render.html_to_text(
        """
        <html>
          <head><style>.x{}</style><title>ignored</title></head>
          <body>
            <p>Hello&nbsp;<strong>World</strong></p>
            <a href="https://example.com">Example</a>
            <script>alert("ignored")</script>
          </body>
        </html>
        """
    )

    assert "Hello" in text
    assert "World" in text
    assert "Example <https://example.com>" in text
    assert "ignored" not in text


def test_unwrap_safelinks_in_text_rewrites_embedded_safelinks():
    text = render.unwrap_safelinks_in_text(
        "Open https://eur01.safelinks.protection.outlook.com/?url=https%3A%2F%2Fexample.org"
    )

    assert text == "Open https://example.org"
