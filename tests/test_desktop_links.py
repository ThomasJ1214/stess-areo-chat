"""Source-link boundaries without importing Qt or launching a desktop."""
import pytest

from rocket_workbench.main import _public_https_external_url


SESSION_TOKEN = "native-test-session-private-value"


@pytest.mark.parametrize(("url", "allowed"), [
    ("https://www.thrustcurve.org/motors/AeroTech/J350W/", True),
    ("https://github.com/ThomasJ1214/stess-areo-chat", True),
    ("file:///tmp/private-project.rocket", False),
    ("http://www.thrustcurve.org/motors/", False),
    ("https://127.0.0.1/", False),
    ("https://[::1]/", False),
    ("https://localhost/", False),
    ("https://127.1/", False),
    ("https://0x7f000001/", False),
    ("https://internal.local/", False),
    ("https://10.0.0.1/", False),
    ("https://www.thrustcurve.org/?token=private", False),
    ("https://www.thrustcurve.org/#session_token=private", False),
    (f"https://www.thrustcurve.org/{SESSION_TOKEN}", False),
    ("https://user:secret@www.thrustcurve.org/", False),
])
def test_external_source_links_preserve_local_session_boundary(url, allowed):
    assert _public_https_external_url(url, SESSION_TOKEN) is allowed
