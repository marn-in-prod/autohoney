"""Scanner module — identifies honeypot candidate targets in a codebase."""

from pipeline.scanner.models import ScanConfig, ScanResult, Candidate
from pipeline.scanner.scanner import scan_codebase, write_scan_yaml, read_scan_yaml

__all__ = [
    "ScanConfig",
    "ScanResult",
    "Candidate",
    "scan_codebase",
    "write_scan_yaml",
    "read_scan_yaml",
]
