from consumer.config import parse_logins


def test_parse_logins():
    assert parse_logins(" leopubcode, Other-User ,,") == frozenset({"leopubcode", "other-user"})
    assert parse_logins(" , ") == frozenset()
