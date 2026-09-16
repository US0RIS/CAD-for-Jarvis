from __future__ import annotations

"""Offline acceptance for ForgeCAD 6.2 provider/runtime hardening."""

import json
import socket

from . import component_fidelity as fidelity
from . import component_fidelity_runtime as runtime


def run() -> dict:
    runtime.install()

    # Public-network validation is DNS aware. A hostname that resolves to any private
    # destination is rejected rather than handed to urllib, closing the obvious custom
    # asset-source SSRF path while preserving normal public vendor hosts.
    original_getaddrinfo = socket.getaddrinfo
    try:
        socket.getaddrinfo = lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))
        ]
        assert runtime._safe_remote_url_dns('https://vendor.example/cad/part.step') is True

        socket.getaddrinfo = lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))
        ]
        assert runtime._safe_remote_url_dns('https://vendor.example/cad/part.step') is False

        socket.getaddrinfo = lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.7', 443)),
        ]
        assert runtime._safe_remote_url_dns('https://vendor.example/cad/part.step') is False
    finally:
        socket.getaddrinfo = original_getaddrinfo

    assert runtime._safe_remote_url_dns('http://example.com/part.step') is False
    assert runtime._safe_remote_url_dns('https://127.0.0.1/part.step') is False
    assert runtime._safe_remote_url_dns('https://localhost/part.step') is False

    fixture = {
        'id': 'fixture.vendor.strict-links',
        'manufacturer': 'Fixture',
        'model': 'STRICT-42',
        'manufacturer_part_number': 'STRICT-42',
    }
    payload = b'''<html><body>
      <a href="/product/strict-42#downloads">Downloads</a>
      <a href="/drawing/strict-42.pdf">Dimension drawing</a>
      <a href="/cad/STRICT-42.step">Download</a>
      <a href="/cad/STRICT-42-3d.zip">3D CAD</a>
      <a href="/locale/strict-42">3D printer product page</a>
    </body></html>'''
    # A literal public test address keeps this acceptance completely offline.
    links = runtime._strict_cad_links('https://93.184.216.34/product/strict-42', payload, fixture)
    assert 'https://93.184.216.34/cad/STRICT-42.step' in links
    assert 'https://93.184.216.34/cad/STRICT-42-3d.zip' in links
    assert not any('#downloads' in url for url in links)
    assert not any(url.endswith('.pdf') for url in links)
    assert not any('/locale/' in url for url in links)

    noctua = fidelity.AUTHORITATIVE_SOURCES[runtime._NOCTUA_COMPONENT_ID][0]
    assert noctua.direct is True and 'cdn.noctua.at' in noctua.url and 'NF-A4x10_Public-CAD.zip' in noctua.url
    meanwell = fidelity.AUTHORITATIVE_SOURCES[runtime._MEANWELL_COMPONENT_ID][0]
    assert meanwell.kind == 'authorized_distributor' and 'transmotec.com/product/LRS-75-12' in meanwell.url
    stepper = fidelity.AUTHORITATIVE_SOURCES[runtime._STEPPER_COMPONENT_ID][0]
    assert stepper.kind == 'manufacturer' and stepper.url == runtime._STEPPER_PRODUCT_URL

    revision_a = runtime.asset_revision()
    revision_b = runtime.asset_revision()
    assert revision_a['epoch'] == revision_b['epoch'] and revision_a['epoch']
    assert revision_a['generation'] == revision_b['generation']

    return {
        'ok': True,
        'version': '6.2.0',
        'checks': {
            'dns_private_targets_rejected': True,
            'mixed_dns_targets_rejected': True,
            'strict_cad_candidate_filtering': True,
            'direct_noctua_cdn_source': True,
            'meanwell_authorized_distributor_source': True,
            'stepper_session_source_binding': True,
            'stable_process_epoch': True,
        },
        'asset_revision': revision_a,
    }


if __name__ == '__main__':
    print(json.dumps(run(), indent=2))
