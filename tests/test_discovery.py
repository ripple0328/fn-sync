import contextlib
import importlib.util
import io
import ipaddress
import json
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

    def test_discover_scans_only_local_hosts_and_collects_open_ports(self):
        network = ipaddress.ip_network("192.168.50.0/30")

        def port_is_open(host, port):
            return host == "192.168.50.1" and port in {5667, 5006}

        def describe(host, ports):
            return {"address": host, "ports": sorted(ports)}

        with mock.patch.object(
            discovery, "local_private_networks", return_value=[network]
        ), mock.patch.object(
            discovery, "_tcp_open", side_effect=port_is_open
        ), mock.patch.object(
            discovery, "inspect_host", side_effect=describe
        ) as inspect_host:
            payload = discovery.discover()
        self.assertEqual(payload["networks"], ["192.168.50.0/30"])
        self.assertEqual(
            payload["devices"],
            [{"address": "192.168.50.1", "ports": [5006, 5667]}],
        )
        inspect_host.assert_called_once_with("192.168.50.1", {5006, 5667})

    def test_http_probe_closes_connections_on_success_and_failure(self):
        response = mock.Mock()
        response.status = 207
        response.getheaders.return_value = [("DAV", "1, 2")]
        response.read.return_value = b"response"
        connection = mock.Mock()
        connection.getresponse.return_value = response
        with mock.patch.object(
            discovery.http.client, "HTTPSConnection", return_value=connection
        ), mock.patch.object(discovery.ssl, "_create_unverified_context"):
            result = discovery._request("192.168.1.2", 5006, "https", "OPTIONS")
        self.assertEqual(result.status, 207)
        self.assertEqual(result.header("DAV"), "1, 2")
        connection.request.assert_called_once()
        connection.close.assert_called_once()

        failed = mock.Mock()
        failed.request.side_effect = OSError("offline")
        with mock.patch.object(
            discovery.http.client, "HTTPConnection", return_value=failed
        ):
            self.assertEqual(
                discovery._request("192.168.1.3", 5005, "http", "GET"),
                discovery.ProbeResult(),
            )
        failed.close.assert_called_once()

    def test_main_returns_machine_readable_success_and_failure(self):
        with mock.patch.object(
            discovery, "discover", return_value={"networks": [], "devices": []}
        ), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(discovery.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["devices"], [])

        with mock.patch.object(
            discovery, "discover", side_effect=RuntimeError("scan failed")
        ), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(discovery.main(), 1)
        self.assertEqual(json.loads(output.getvalue())["error"], "scan failed")


if __name__ == "__main__":
    unittest.main()
