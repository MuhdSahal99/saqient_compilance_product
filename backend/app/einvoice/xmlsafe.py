"""Safe XML parsing for e-invoices and XSD bundles.

Every document is parsed twice: first by defusedxml, which rejects DTDs,
entity declarations and external references outright, then by lxml with a
locked-down parser (no entity resolution, no network, no DTD loading) so that
XPath, XSD validation and source line numbers are available for evidence.
XSD imports and includes resolve only inside the uploaded bundle.
"""

from __future__ import annotations

import io
import posixpath
import zipfile
from functools import lru_cache
from typing import Any

from defusedxml import ElementTree as DET
from lxml import etree

MAX_XML_BYTES = 5 * 1024 * 1024
BUNDLE_MAX_ENTRIES = 500
BUNDLE_MAX_UNCOMPRESSED = 50 * 1024 * 1024
BUNDLE_ALLOWED = (".xsd", ".xml", ".txt", ".md")
BUNDLE_SCHEME = "bundle:///"


class UnsafeXML(ValueError):
    """The bytes are not acceptable XML (message safe to show)."""


def _parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        dtd_validation=False,
        huge_tree=False,
        remove_blank_text=False,
    )


def parse_xml(data: bytes) -> Any:
    """Parse untrusted XML bytes into an lxml element (raises UnsafeXML)."""
    if len(data) > MAX_XML_BYTES:
        raise UnsafeXML(f"The XML file is larger than {MAX_XML_BYTES // (1024 * 1024)} MB.")
    try:
        DET.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except Exception as exc:  # defusedxml raises on DTDs, entities and malformed XML
        raise UnsafeXML(
            "The file is not well-formed XML, or it uses a DTD or entities, which are not allowed."
        ) from exc
    try:
        return etree.fromstring(data, _parser())
    except etree.XMLSyntaxError as exc:
        raise UnsafeXML("The file is not well-formed XML.") from exc


def read_bundle(data: bytes) -> dict[str, bytes]:
    """Unpack an XSD bundle ZIP with size, count, type and path checks."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UnsafeXML("The schema bundle is not a ZIP file.") from exc
    infos = [i for i in zf.infolist() if not i.is_dir()]
    if not infos:
        raise UnsafeXML("The schema bundle is empty.")
    if len(infos) > BUNDLE_MAX_ENTRIES:
        raise UnsafeXML(f"The schema bundle has more than {BUNDLE_MAX_ENTRIES} files.")
    if sum(i.file_size for i in infos) > BUNDLE_MAX_UNCOMPRESSED:
        raise UnsafeXML("The schema bundle is too large when unpacked.")
    files: dict[str, bytes] = {}
    for info in infos:
        name = posixpath.normpath(info.filename.replace("\\", "/"))
        if name.startswith(("/", "../")) or name == ".." or ":" in name:
            raise UnsafeXML("The schema bundle contains an unsafe path.")
        if not name.lower().endswith(BUNDLE_ALLOWED):
            raise UnsafeXML(f"The schema bundle may only contain {', '.join(BUNDLE_ALLOWED)}.")
        body = zf.read(info)
        if len(body) != info.file_size:
            raise UnsafeXML("The schema bundle is corrupt.")
        files[name] = body
    return files


class _BundleResolver(etree.Resolver):
    def __init__(self, files: dict[str, bytes]) -> None:
        super().__init__()
        self.files = files

    def resolve(self, url: str, pubid: str | None, context: Any) -> Any:
        if not url.startswith(BUNDLE_SCHEME):
            raise UnsafeXML("Schemas may only import files from their own bundle.")
        name = posixpath.normpath(url[len(BUNDLE_SCHEME) :])
        body = self.files.get(name)
        if body is None:
            raise UnsafeXML(f"The schema bundle has no file '{name}'.")
        return self.resolve_string(body, context, base_url=url)


def compile_schema(files: dict[str, bytes], entry_point: str) -> etree.XMLSchema:
    if entry_point not in files:
        raise UnsafeXML(f"The schema bundle has no file '{entry_point}'.")
    for name, body in files.items():
        if name.endswith(".xsd"):
            parse_xml(body)  # every schema file passes the same safety checks
    parser = _parser()
    parser.resolvers.add(_BundleResolver(files))
    try:
        doc = etree.fromstring(files[entry_point], parser, base_url=BUNDLE_SCHEME + entry_point)
        return etree.XMLSchema(etree.ElementTree(doc))
    except UnsafeXML:
        raise
    except (etree.XMLSchemaParseError, etree.XMLSyntaxError) as exc:
        cause = exc.__context__
        if isinstance(cause, UnsafeXML):
            raise cause from exc
        raise UnsafeXML("The schema bundle does not compile as XSD.") from exc


@lru_cache(maxsize=16)
def cached_schema(sha256: str, data: bytes, entry_point: str) -> etree.XMLSchema:
    """Compiled schema keyed by bundle hash (the bytes are immutable for a hash)."""
    return compile_schema(read_bundle(data), entry_point)
