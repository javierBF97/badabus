import unittest

from badabus import bus_data_api as api


class TestFetchJson(unittest.TestCase):
    def test_returns_data_on_ok(self):
        def fake(url, timeout=10):
            assert "action=lineas" in url
            return b'{"ok":true,"data":[{"lin":"2"}]}'
        self.assertEqual(api.fetch_json("lineas", fetch=fake), [{"lin": "2"}])

    def test_passes_params_in_url(self):
        seen = {}
        def fake(url, timeout=10):
            seen["url"] = url
            return b'{"ok":true,"data":[]}'
        api.fetch_json("paradas", fetch=fake, linea="TRIP_100007")
        self.assertIn("action=paradas", seen["url"])
        self.assertIn("linea=TRIP_100007", seen["url"])

    def test_raises_when_not_ok(self):
        def fake(url, timeout=10):
            return b'{"ok":false}'
        with self.assertRaises(ValueError):
            api.fetch_json("lineas", fetch=fake)

    def test_raises_when_ok_but_no_data(self):
        def fake(url, timeout=10):
            return b'{"ok":true}'
        with self.assertRaises(ValueError):
            api.fetch_json("lineas", fetch=fake)


if __name__ == "__main__":
    unittest.main()
