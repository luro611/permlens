"""Eigenes HTTPS-Zertifikat von PermLens (ab 0.2.2).

Beim ersten Start erzeugt PermLens in data/tls/ einen Schlüssel und ein selbst ausgestelltes Zertifikat
(10 Jahre gültig). Der Browser warnt beim ersten Besuch, weil keine Zertifizierungsstelle unterschrieben hat.
Prüfen lässt sich das Zertifikat trotzdem: Die Einstellungsseite zeigt seinen Fingerabdruck, und der
Einrichtungs-Befehl für den Proxmox legt den Schlüssel fest (curl --pinnedpubkey). Proxmox spricht dann
nur mit genau diesem PermLens."""
import base64
import hashlib
import os
import re
import ssl
import subprocess

from . import config

PIN_OK = re.compile(r'^[A-Za-z0-9+/]{43}=$')


def _dir():
    return config.DATA / 'tls'


def paths():
    d = _dir()
    return d / 'key.pem', d / 'cert.pem', d / 'pin.txt'


def enabled():
    key, cert, pin = paths()
    return key.exists() and cert.exists() and pin.exists()


def ensure():
    """Schlüssel, Zertifikat und Pin anlegen, falls sie fehlen. Braucht das Programm openssl."""
    if enabled():
        return
    key, cert, pin = paths()
    key.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(key.parent, 0o700)
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:prime256v1', '-nodes',
                    '-days', '3650', '-subj', '/CN=PermLens', '-addext', 'subjectAltName=DNS:permlens',
                    '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True, timeout=60)
    os.chmod(key, 0o600)
    pub = subprocess.run(['openssl', 'x509', '-in', str(cert), '-pubkey', '-noout'],
                         check=True, capture_output=True, timeout=30).stdout
    der = subprocess.run(['openssl', 'pkey', '-pubin', '-outform', 'der'], input=pub,
                         check=True, capture_output=True, timeout=30).stdout
    pin.write_text(base64.b64encode(hashlib.sha256(der).digest()).decode() + '\n')


def pin():
    """SHA-256 des öffentlichen Schlüssels (Base64), für curl --pinnedpubkey sha256//…"""
    try:
        p = paths()[2].read_text().strip()
    except OSError:
        return ''
    return p if PIN_OK.match(p) else ''


def fingerprint():
    """SHA-256-Fingerabdruck des Zertifikats, wie ihn Browser anzeigen (AB:CD:…)."""
    try:
        der = ssl.PEM_cert_to_DER_cert(paths()[1].read_text())
    except (OSError, ValueError):
        return ''
    h = hashlib.sha256(der).hexdigest().upper()
    return ':'.join(h[i:i + 2] for i in range(0, len(h), 2))
