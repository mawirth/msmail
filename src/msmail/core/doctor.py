from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Optional

from msmail.core import auth
from msmail.core import graph
from msmail.core import smime


@dataclass(frozen=True)
class DoctorLine:
    name: str
    status: str
    detail: str | None = None


@dataclass(frozen=True)
class DoctorReport:
    ok: bool
    lines: list[DoctorLine]


def _version() -> str:
    try:
        return metadata.version("msmail")
    except metadata.PackageNotFoundError:
        return "unknown"


def _openssl_version() -> tuple[str, str | None]:
    if not shutil.which("openssl"):
        return "MISSING", "not found in PATH"

    try:
        result = subprocess.run(
            ["openssl", "version"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        return "ERROR", str(exc)

    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        return "ERROR", output or f"exit code {result.returncode}"
    return "OK", output or None


def _temp_dir_status() -> tuple[str, str]:
    directory = tempfile.gettempdir()
    try:
        with tempfile.TemporaryFile(dir=directory):
            pass
    except Exception as exc:
        return "ERROR", f"{directory} ({exc})"
    return "OK", directory


def _recipients_count(recipients_dir: str) -> int:
    path = Path(recipients_dir)
    if not path.is_dir():
        return 0
    return sum(1 for item in path.iterdir() if item.is_file() and item.suffix.lower() == ".pem")


def _signature_path(account_email: str, suffix: str) -> Path:
    return auth.account_dir(account_email) / f"signature.{suffix}"


def check(account_email: Optional[str] = None) -> DoctorReport:
    lines = [
        DoctorLine("Python", "OK", sys.version.split()[0]),
        DoctorLine("msmail", "OK", _version()),
    ]

    active_account = account_email.strip().lower() if account_email else auth.active_email()
    if active_account:
        lines.append(DoctorLine("Account", "OK", active_account))
    else:
        lines.append(DoctorLine("Account", "MISSING", "run: msmail auth --login <email>"))

    token: str | None = None
    if active_account:
        try:
            token, resolved_account = auth.get_access_token(active_account)
            lines.append(DoctorLine("Token", "OK", resolved_account.email))
        except Exception as exc:
            lines.append(DoctorLine("Token", "ERROR", str(exc)))
    else:
        lines.append(DoctorLine("Token", "SKIP", "no active account"))

    if token:
        try:
            graph.get_json("/me", token, params={"$select": "id,mail,userPrincipalName"})
            lines.append(DoctorLine("Graph", "OK"))
        except Exception as exc:
            lines.append(DoctorLine("Graph", "ERROR", str(exc)))
    else:
        lines.append(DoctorLine("Graph", "SKIP", "no token"))

    openssl_status, openssl_detail = _openssl_version()
    lines.append(DoctorLine("OpenSSL", openssl_status, openssl_detail))

    if active_account:
        try:
            smime_paths = smime.smime_paths(active_account)
            lines.append(DoctorLine("S/MIME cert", "OK" if Path(smime_paths.cert).exists() else "MISSING", smime_paths.cert))
            lines.append(DoctorLine("S/MIME key", "OK" if Path(smime_paths.key).exists() else "MISSING", smime_paths.key))
            lines.append(
                DoctorLine("CA bundle", "OK" if Path(smime_paths.ca_bundle).exists() else "MISSING", smime_paths.ca_bundle)
            )
            recipients = _recipients_count(smime_paths.recipients_dir)
            lines.append(DoctorLine("Recipients", "OK", f"{recipients} imported"))
        except Exception as exc:
            lines.append(DoctorLine("S/MIME cert", "ERROR", str(exc)))
            lines.append(DoctorLine("S/MIME key", "SKIP", "S/MIME status unavailable"))
            lines.append(DoctorLine("CA bundle", "SKIP", "S/MIME status unavailable"))
            lines.append(DoctorLine("Recipients", "SKIP", "S/MIME status unavailable"))
    else:
        lines.append(DoctorLine("S/MIME cert", "SKIP", "no active account"))
        lines.append(DoctorLine("S/MIME key", "SKIP", "no active account"))
        lines.append(DoctorLine("CA bundle", "SKIP", "no active account"))
        lines.append(DoctorLine("Recipients", "SKIP", "no active account"))

    if active_account:
        text_signature = _signature_path(active_account, "txt")
        html_signature = _signature_path(active_account, "html")
        lines.append(DoctorLine("Signature txt", "OK" if text_signature.exists() else "MISSING", str(text_signature)))
        lines.append(DoctorLine("Signature html", "OK" if html_signature.exists() else "MISSING", str(html_signature)))
    else:
        lines.append(DoctorLine("Signature txt", "SKIP", "no active account"))
        lines.append(DoctorLine("Signature html", "SKIP", "no active account"))

    temp_status, temp_detail = _temp_dir_status()
    lines.append(DoctorLine("Temp dir", temp_status, temp_detail))

    optional_missing = {"Signature txt", "Signature html"}
    ok = all(line.status in {"OK", "SKIP"} or line.name in optional_missing for line in lines)
    return DoctorReport(ok=ok, lines=lines)
