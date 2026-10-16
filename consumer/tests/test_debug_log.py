import os
import time
from datetime import date, datetime, timedelta

from consumer.debug_log import DebugLog


def test_lines_are_appended_to_debug_log(tmp_path):
    log = DebugLog(tmp_path / "debug.log")

    log.write("pane missing", "org/repo:feature/x", "first", pane_id="pane-1")
    log.write("fork PR ignored", "org/repo:-", "second")

    fields = [line.split("\t") for line in (tmp_path / "debug.log").read_text().splitlines()]
    assert [f[1:] for f in fields] == [
        ["org/repo:feature/x", "pane-1", "pane missing", "first"],
        ["org/repo:-", "-", "fork PR ignored", "second"],
    ]
    assert all(f[0].endswith("Z") for f in fields)


def test_nothing_is_created_until_the_first_write(tmp_path):
    DebugLog(tmp_path / "debug.log")

    assert list(tmp_path.iterdir()) == []


def test_yesterdays_lines_are_renamed_to_yesterdays_date(tmp_path):
    path = tmp_path / "debug.log"
    path.write_text("old line\n")
    yesterday = date.today() - timedelta(days=1)
    noon = time.mktime(datetime.combine(yesterday, datetime.min.time()).replace(hour=12).timetuple())
    os.utime(path, (noon, noon))

    DebugLog(path).write("pane missing", "org/repo:b", "today")

    assert (tmp_path / f"debug.log.{yesterday:%Y-%m-%d}").read_text() == "old line\n"
    assert "today" in path.read_text()
    assert "old line" not in path.read_text()
