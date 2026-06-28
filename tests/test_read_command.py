from msmail.core import mime


def test_body_from_mime_extracts_text_from_multipart_signed():
    mime_bytes = (
        b'Content-Type: multipart/signed; boundary="sig"; protocol="application/pkcs7-signature"\r\n'
        b"\r\n"
        b"--sig\r\n"
        b"Content-Type: multipart/mixed; boundary=\"mix\"\r\n"
        b"\r\n"
        b"--mix\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"secret body\r\n"
        b"--mix\r\n"
        b"Content-Type: text/plain\r\n"
        b"Content-Disposition: attachment; filename=\"report.txt\"\r\n"
        b"\r\n"
        b"attachment\r\n"
        b"--mix--\r\n"
        b"--sig\r\n"
        b"Content-Type: application/pkcs7-signature; name=\"smime.p7s\"\r\n"
        b"Content-Disposition: attachment; filename=\"smime.p7s\"\r\n"
        b"\r\n"
        b"signature\r\n"
        b"--sig--\r\n"
    )

    body, content_type, attachments = mime.body_from_mime(mime_bytes, raw_html=False)

    assert body == "secret body"
    assert content_type == "plain"
    assert attachments == ["report.txt", "smime.p7s"]


def test_body_from_mime_renders_html_when_text_is_unavailable():
    mime_bytes = (
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"\r\n"
        b"<p>Hello<br>Alex</p>"
    )

    body, content_type, attachments = mime.body_from_mime(mime_bytes, raw_html=False)

    assert body == "Hello\n\nAlex"
    assert content_type == "html"
    assert attachments == []
