from aigfs import common


def test_common_platforms():
    assert common.platforms() == ["oci", "ursa", "wcoss2"]
