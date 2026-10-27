from herdr_slack.store import PaneRef, ThreadStore


def test_store_persists_across_instances(tmp_path):
    ThreadStore(tmp_path / "s.json").put("1.0", PaneRef("w:p1", "t1"))
    assert ThreadStore(tmp_path / "s.json").get("1.0") == PaneRef("w:p1", "t1")


def test_store_missing_file_starts_empty(tmp_path):
    assert ThreadStore(tmp_path / "none.json").get("1.0") is None


def test_store_keeps_latest_500(tmp_path):
    s = ThreadStore(tmp_path / "s.json")
    for i in range(510):
        s.put(f"{i}.0", PaneRef("p", "t"))
    s2 = ThreadStore(tmp_path / "s.json")
    assert s2.get("0.0") is None and s2.get("509.0") == PaneRef("p", "t")
