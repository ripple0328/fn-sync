import importlib.util
import ipaddress
import sys
import unittest
from pathlib import Path
from unittest import mock

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "omarchy-plugin"
    / "scripts"
    / "fn_sync_discover.py"
)
SPEC = importlib.util.spec_from_file_location("fn_sync_discover_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
discovery = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = discovery
SPEC.loader.exec_module(discovery)


class DiscoveryTests(unittest.TestCase):
    def test_large_private_route_is_bounded_to_source_subnet(self):
        routes = [{"dst": "10.0.0.0/8", "prefsrc": "10.23.45.67"}]
        with mock.patch.object(discovery, "_run_ip_json", return_value=routes):
            self.assertEqual(
                discovery.local_private_networks(),
                [ipaddress.ip_network("10.23.45.0/24")],
            )

    def test_management_host_does_not_claim_closed_default_webdav_port(self):
        result = discovery.ProbeResult(
            status=200,
            headers=(("Server", "fnOS"),),
            body=b"<title>fnOS</title>",
        )
        with mock.patch.object(discovery, "_request", return_value=result):
            device = discovery.inspect_host("192.168.1.20", {5667})
        self.assertIsNotNone(device)
        self.assertEqual(device["management_url"], "https://192.168.1.20:5667/")
        self.assertEqual(device["url"], "")
        self.assertEqual(device["suggested_url"], "https://192.168.1.20:5006/")
        self.assertFalse(device["webdav_verified"])
        self.assertFalse(device["insecure_skip_verify"])

    def test_unrelated_web_server_is_not_reported_as_nas(self):
        result = discovery.ProbeResult(status=200, headers=(("Server", "nginx"),))
        with mock.patch.object(discovery, "_request", return_value=result):
            self.assertIsNone(discovery.inspect_host("192.168.1.30", {5006}))

    def test_webdav_response_is_reported_without_management_port(self):
        result = discovery.ProbeResult(status=401, headers=(("DAV", "1, 2"),))
        with mock.patch.object(discovery, "_request", return_value=result):
            device = discovery.inspect_host("192.168.1.40", {5006})
        self.assertIsNotNone(device)
        self.assertTrue(device["webdav_verified"])
        self.assertEqual(device["url"], "https://192.168.1.40:5006/")


if __name__ == "__main__":
    unittest.main()
