from email.message import EmailMessage

import pytest

from msmail.core import mime


@pytest.mark.parametrize('raw_html,expected,content_type', [
    (False, 'Plain alternative', 'plain'),
    (True, '<p>HTML alternative</p>', 'html'),
])
def test_alternative_prefers_requested_type(raw_html, expected, content_type):
    message = EmailMessage()
    message.set_content('Plain alternative')
    message.add_alternative('<p>HTML alternative</p>', subtype='html')
    body, kind, _ = mime.body_from_mime(message.as_bytes(), raw_html)
    assert body.strip() == expected
    assert kind == content_type


@pytest.mark.parametrize('subtype,raw_html', [('html', False), ('plain', True)])
def test_missing_preferred_type_uses_fallback(subtype, raw_html):
    message = EmailMessage()
    message.set_content('Fallback', subtype=subtype)
    body, _, _ = mime.body_from_mime(message.as_bytes(), raw_html)
    assert body.strip() == 'Fallback'


def test_attached_message_is_not_used_as_body():
    attached = EmailMessage()
    attached.set_content('Attached text is not the body')
    message = EmailMessage()
    message.set_content('<p>Actual body</p>', subtype='html')
    message.add_attachment(attached)
    body, _, _ = mime.body_from_mime(message.as_bytes(), False)
    assert body == 'Actual body'
