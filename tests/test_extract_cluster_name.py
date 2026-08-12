import unittest

from ytsaurus_python_client.hook import YTsaurusHook


class TestExtractClusterName(unittest.TestCase):
    def test_standard_proxy(self):
        self.assertEqual(
            YTsaurusHook._extract_cluster_name("hahn.yt.example.com"),
            "hahn",
        )

    def test_alternative_proxy(self):
        self.assertEqual(
            YTsaurusHook._extract_cluster_name("hahn.yt.proxy.example.com"),
            "hahn",
        )

    def test_http_proxy_mirror(self):
        self.assertEqual(
            YTsaurusHook._extract_cluster_name("51.http-proxy.hahn-yt.example.com"),
            "hahn",
        )

    def test_http_proxy_without_yt_suffix(self):
        self.assertEqual(
            YTsaurusHook._extract_cluster_name("some-proxy.host.example.com"),
            "some-proxy",
        )

    def test_bare_hostname(self):
        self.assertEqual(
            YTsaurusHook._extract_cluster_name("hahn"),
            "hahn",
        )

    def test_cluster_proxy(self):
        self.assertEqual(
            YTsaurusHook._extract_cluster_name("arnold.yt.example.com"),
            "arnold",
        )

    def test_cluster_http_proxy(self):
        self.assertEqual(
            YTsaurusHook._extract_cluster_name("42.http-proxy.arnold-yt.example.com"),
            "arnold",
        )

    def test_segment_without_yt_suffix_not_matched(self):
        self.assertEqual(
            YTsaurusHook._extract_cluster_name("myproxy.bigdata.internal"),
            "myproxy",
        )

    def test_explicit_cluster_name_override(self):
        hook = YTsaurusHook(
            yt_proxy="51.http-proxy.hahn-yt.example.com",
            yt_cluster_name="arnold",
        )
        self.assertEqual(hook.yt_cluster_name, "arnold")

    def test_explicit_cluster_via_init(self):
        hook = YTsaurusHook(
            yt_proxy="51.http-proxy.hahn-yt.example.com",
        )
        self.assertEqual(hook.yt_cluster_name, "hahn")


if __name__ == "__main__":
    unittest.main()
