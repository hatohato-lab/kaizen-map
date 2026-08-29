import sys; sys.path.insert(0, "../src")
def test_normalize():
    from utils import normalize
    assert normalize(" A ") == "a"
