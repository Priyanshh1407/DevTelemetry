"""Self-tests for the conftest guards, so 'no network, no real DB' is proven rather than assumed."""
import socket

import pytest

from core.db import get_db_path


def test_outbound_network_is_blocked():
    with pytest.raises(RuntimeError, match="Network access blocked"):
        socket.create_connection(("93.184.215.14", 443), timeout=1)


def test_db_path_points_at_tmp_db(empty_db):
    assert get_db_path() == str(empty_db)


def test_gemini_client_is_mocked(mock_gemini):
    import ai.guide_generator as gg

    assert gg.client is mock_gemini
