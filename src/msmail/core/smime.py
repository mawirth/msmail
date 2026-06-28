from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Optional

from msmail.core import auth


@dataclass(frozen=True)
class SmimePaths:
    account: str
    directory: str
    cert: str
    key: str
    ca_bundle: str
    fullchain: str
    recipients_dir: str


@dataclass(frozen=True)
class CertificateInfo:
    subject: str
    issuer: str
    not_before: str
    not_after: str
    emails: list[str]
    email_protection: bool


@dataclass(frozen=True)
class SmimeStatus:
    account: str
    directory: str
    cert_exists: bool
    key_exists: bool
    ca_bundle_exists: bool
    fullchain_exists: bool
    recipients_dir_exists: bool
    certificate: Optional[CertificateInfo]


@dataclass(frozen=True)
class SmimeSetupResult:
    account: str
    paths: SmimePaths
    certificate: CertificateInfo


@dataclass(frozen=True)
class RecipientImportResult:
    account: str
    email: str
    path: str
    certificate: CertificateInfo


@dataclass(frozen=True)
class LocalSignVerifyResult:
    account: str
    unsigned_path: str
    signed_path: str
    verified_path: str
    verified: bool


@dataclass(frozen=True)
class VerifyResult:
    verified: bool
    signed: bool
    verified_path: str
    signer_path: str | None = None
    signer_certificate: CertificateInfo | None = None
    error: str | None = None


@dataclass(frozen=True)
class DecryptResult:
    decrypted: bool
    encrypted_path: str
    decrypted_path: str
    error: str | None = None


def resolve_account_email(account_email: Optional[str] = None) -> str:
    if account_email:
        return account_email.strip().lower()
    active = auth.active_email()
    if not active:
        raise RuntimeError("No active account. Run: msmail auth --login <email>")
    return active


def smime_dir(account_email: str) -> Path:
    return auth.account_dir(account_email) / "smime"


def smime_paths(account_email: str) -> SmimePaths:
    directory = smime_dir(account_email)
    return SmimePaths(
        account=account_email,
        directory=str(directory),
        cert=str(directory / "own-cert.pem"),
        key=str(directory / "own-key.pem"),
        ca_bundle=str(directory / "ca-bundle.pem"),
        fullchain=str(directory / "own-fullchain.p12"),
        recipients_dir=str(directory / "recipients"),
    )


def _run_openssl(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["openssl"] + args,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("openssl not found in PATH.") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ValueError(f"openssl failed: {detail}")
    return result.stdout


def _run_openssl_file(args: list[str]) -> None:
    _run_openssl(args)


def certificate_info(path: str | Path) -> CertificateInfo:
    cert_path = str(path)
    metadata = _run_openssl(
        ["x509", "-in", cert_path, "-noout", "-subject", "-issuer", "-dates", "-ext", "extendedKeyUsage"]
    )
    emails_output = _run_openssl(["x509", "-in", cert_path, "-noout", "-email"])

    subject = ""
    issuer = ""
    not_before = ""
    not_after = ""
    email_protection = False
    for raw_line in metadata.splitlines():
        line = raw_line.strip()
        if line.startswith("subject="):
            subject = line.removeprefix("subject=").strip()
        elif line.startswith("issuer="):
            issuer = line.removeprefix("issuer=").strip()
        elif line.startswith("notBefore="):
            not_before = line.removeprefix("notBefore=").strip()
        elif line.startswith("notAfter="):
            not_after = line.removeprefix("notAfter=").strip()
        elif "E-mail Protection" in line:
            email_protection = True

    emails = [line.strip().lower() for line in emails_output.splitlines() if line.strip()]
    return CertificateInfo(
        subject=subject,
        issuer=issuer,
        not_before=not_before,
        not_after=not_after,
        emails=emails,
        email_protection=email_protection,
    )


def _copy_file(source: str, target: Path, mode: int) -> None:
    source_path = Path(source).expanduser()
    if not source_path.exists():
        raise ValueError(f"File not found: {source}")
    if not source_path.is_file():
        raise ValueError(f"Not a file: {source}")
    shutil.copyfile(source_path, target)
    target.chmod(mode)


def _copy_cert(source: str | Path, target: Path) -> None:
    source_path = Path(source).expanduser()
    if not source_path.exists():
        raise ValueError(f"File not found: {source}")
    if not source_path.is_file():
        raise ValueError(f"Not a file: {source}")
    shutil.copyfile(source_path, target)
    target.chmod(0o600)


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)


def setup(
    *,
    cert: str,
    key: str,
    ca_bundle: str,
    fullchain: Optional[str] = None,
    account_email: Optional[str] = None,
) -> SmimeSetupResult:
    account_email = resolve_account_email(account_email)
    info = certificate_info(Path(cert).expanduser())
    if account_email not in info.emails:
        raise ValueError(
            f"Certificate email does not match account {account_email}. "
            f"Certificate emails: {', '.join(info.emails) or '(none)'}"
        )
    if not info.email_protection:
        raise ValueError("Certificate is missing Extended Key Usage: E-mail Protection.")

    directory = smime_dir(account_email)
    recipients = directory / "recipients"
    _ensure_private_dir(directory)
    _ensure_private_dir(recipients)

    paths = smime_paths(account_email)
    _copy_file(cert, Path(paths.cert), 0o600)
    _copy_file(key, Path(paths.key), 0o600)
    _copy_file(ca_bundle, Path(paths.ca_bundle), 0o600)
    if fullchain:
        _copy_file(fullchain, Path(paths.fullchain), 0o600)

    return SmimeSetupResult(
        account=account_email,
        paths=paths,
        certificate=info,
    )


def _recipient_filename(email: str) -> str:
    return email.strip().lower()


def import_recipient_certificate(
    *,
    cert: str,
    email: Optional[str] = None,
    account_email: Optional[str] = None,
) -> RecipientImportResult:
    account_email = resolve_account_email(account_email)
    paths = smime_paths(account_email)
    recipients_dir = Path(paths.recipients_dir)
    _ensure_private_dir(recipients_dir)

    info = certificate_info(Path(cert).expanduser())
    if not info.email_protection:
        raise ValueError("Certificate is missing Extended Key Usage: E-mail Protection.")

    target_email = (email or (info.emails[0] if info.emails else "")).strip().lower()
    if not target_email:
        raise ValueError("Recipient certificate has no email address; pass --email explicitly.")
    if info.emails and target_email not in info.emails:
        raise ValueError(
            f"Certificate email does not match recipient {target_email}. "
            f"Certificate emails: {', '.join(info.emails)}"
        )

    target = recipients_dir / f"{_recipient_filename(target_email)}.pem"
    _copy_cert(cert, target)
    return RecipientImportResult(
        account=account_email,
        email=target_email,
        path=str(target),
        certificate=info,
    )


def status(account_email: Optional[str] = None) -> SmimeStatus:
    account_email = resolve_account_email(account_email)
    paths = smime_paths(account_email)
    cert_path = Path(paths.cert)
    cert_info = certificate_info(cert_path) if cert_path.exists() else None
    return SmimeStatus(
        account=account_email,
        directory=paths.directory,
        cert_exists=cert_path.exists(),
        key_exists=Path(paths.key).exists(),
        ca_bundle_exists=Path(paths.ca_bundle).exists(),
        fullchain_exists=Path(paths.fullchain).exists(),
        recipients_dir_exists=Path(paths.recipients_dir).is_dir(),
        certificate=cert_info,
    )


def require_configured(account_email: Optional[str] = None) -> tuple[str, SmimePaths]:
    account_email = resolve_account_email(account_email)
    paths = smime_paths(account_email)
    missing = [
        label
        for label, value in [
            ("own certificate", paths.cert),
            ("own private key", paths.key),
            ("CA bundle", paths.ca_bundle),
        ]
        if not Path(value).exists()
    ]
    if missing:
        raise ValueError(f"S/MIME is not configured; missing: {', '.join(missing)}")
    return account_email, paths


def _candidate_recipient_paths(paths: SmimePaths, email: str) -> list[Path]:
    filename = _recipient_filename(email)
    recipients_dir = Path(paths.recipients_dir)
    return [
        recipients_dir / f"{filename}.pem",
        recipients_dir / f"{filename}.cer",
        recipients_dir / f"{filename}.crt",
    ]


def recipient_certificates(
    recipients: list[str],
    *,
    account_email: Optional[str] = None,
) -> list[str]:
    account_email, paths = require_configured(account_email)
    result: list[str] = []
    missing: list[str] = []

    for recipient in sorted({address.strip().lower() for address in recipients if address.strip()}):
        if recipient == account_email:
            cert_path = paths.cert
        else:
            cert_path = ""
            for candidate in _candidate_recipient_paths(paths, recipient):
                if candidate.exists():
                    cert_path = str(candidate)
                    break
        if cert_path:
            if cert_path not in result:
                result.append(cert_path)
        else:
            missing.append(recipient)

    if missing:
        first = missing[0]
        hint = Path(paths.recipients_dir) / f"{_recipient_filename(first)}.pem"
        raise ValueError(
            "Missing S/MIME recipient certificate for "
            f"{', '.join(missing)}. Import one with: "
            f"msmail smime import-recipient --cert <cert.pem> --email {first} "
            f"(or place it at {hint})"
        )

    return result


def build_text_mime(
    *,
    sender: str,
    to: list[str],
    subject: str,
    body: str,
) -> bytes:
    message = EmailMessage(policy=SMTP)
    message["From"] = sender
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message.set_content(body)
    return message.as_bytes(policy=SMTP)


def build_mime_message(
    *,
    sender: str,
    to: list[str],
    cc: list[str],
    bcc: list[str],
    subject: str,
    body: str,
    content_type: str,
    attachments: list[tuple[str, str, bytes]] | None = None,
) -> bytes:
    message = EmailMessage(policy=SMTP)
    message["From"] = sender
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    if bcc:
        message["Bcc"] = ", ".join(bcc)
    message["Subject"] = subject

    if content_type.lower() == "html":
        message.set_content(body, subtype="html")
    else:
        message.set_content(body)

    for filename, mime_type, content in attachments or []:
        maintype, _, subtype = mime_type.partition("/")
        if not maintype or not subtype:
            maintype, subtype = "application", "octet-stream"
        message.add_attachment(
            content,
            maintype=maintype,
            subtype=subtype,
            filename=filename,
        )

    return message.as_bytes(policy=SMTP)


def build_mime_entity(
    *,
    body: str,
    content_type: str,
    attachments: list[tuple[str, str, bytes]] | None = None,
) -> bytes:
    message = EmailMessage(policy=SMTP)
    if content_type.lower() == "html":
        message.set_content(body, subtype="html")
    else:
        message.set_content(body)

    for filename, mime_type, content in attachments or []:
        maintype, _, subtype = mime_type.partition("/")
        if not maintype or not subtype:
            maintype, subtype = "application", "octet-stream"
        message.add_attachment(
            content,
            maintype=maintype,
            subtype=subtype,
            filename=filename,
        )

    return message.as_bytes(policy=SMTP)


def wrap_signed_entity(
    *,
    sender: str,
    to: list[str],
    cc: list[str],
    bcc: list[str],
    subject: str,
    signed_entity: bytes,
) -> bytes:
    message = EmailMessage(policy=SMTP)
    message["From"] = sender
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    if bcc:
        message["Bcc"] = ", ".join(bcc)
    message["Subject"] = subject
    headers = message.as_bytes(policy=SMTP).split(b"\r\n\r\n", 1)[0]
    return headers + b"\r\n" + signed_entity


def wrap_mime_entity(
    *,
    sender: str,
    to: list[str],
    cc: list[str],
    bcc: list[str],
    subject: str,
    entity: bytes,
) -> bytes:
    return wrap_signed_entity(
        sender=sender,
        to=to,
        cc=cc,
        bcc=bcc,
        subject=subject,
        signed_entity=entity,
    )


def sign_mime(
    mime_bytes: bytes,
    *,
    account_email: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> tuple[str, str]:
    _account, paths = require_configured(account_email)
    directory = Path(output_dir).expanduser() if output_dir else Path(tempfile.mkdtemp(prefix="msmail-smime-"))
    directory.mkdir(parents=True, exist_ok=True)
    unsigned_path = directory / "unsigned.eml"
    signed_path = directory / "signed.eml"
    unsigned_path.write_bytes(mime_bytes)
    _run_openssl_file(
        [
            "smime",
            "-sign",
            "-in",
            str(unsigned_path),
            "-signer",
            paths.cert,
            "-inkey",
            paths.key,
            "-certfile",
            paths.ca_bundle,
            "-out",
            str(signed_path),
            "-outform",
            "SMIME",
        ]
    )
    return str(unsigned_path), str(signed_path)


def encrypt_mime(
    mime_bytes: bytes,
    *,
    recipients: list[str],
    account_email: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> tuple[str, str]:
    account_email, _paths = require_configured(account_email)
    certs = recipient_certificates(recipients, account_email=account_email)
    directory = Path(output_dir).expanduser() if output_dir else Path(tempfile.mkdtemp(prefix="msmail-smime-"))
    directory.mkdir(parents=True, exist_ok=True)
    clear_path = directory / "clear.eml"
    encrypted_path = directory / "encrypted.eml"
    clear_path.write_bytes(mime_bytes)
    _run_openssl_file(
        [
            "smime",
            "-encrypt",
            "-aes256",
            "-in",
            str(clear_path),
            "-out",
            str(encrypted_path),
            "-outform",
            "SMIME",
            *certs,
        ]
    )
    return str(clear_path), str(encrypted_path)


def decrypt_mime_bytes(
    mime_bytes: bytes,
    *,
    account_email: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> DecryptResult:
    _account, paths = require_configured(account_email)
    directory = Path(output_dir).expanduser() if output_dir else Path(tempfile.mkdtemp(prefix="msmail-smime-decrypt-"))
    directory.mkdir(parents=True, exist_ok=True)
    encrypted_path = directory / "encrypted.eml"
    decrypted_path = directory / "decrypted.eml"
    encrypted_path.write_bytes(mime_bytes)
    try:
        _run_openssl_file(
            [
                "smime",
                "-decrypt",
                "-in",
                str(encrypted_path),
                "-recip",
                paths.cert,
                "-inkey",
                paths.key,
                "-out",
                str(decrypted_path),
            ]
        )
    except ValueError as exc:
        return DecryptResult(
            decrypted=False,
            encrypted_path=str(encrypted_path),
            decrypted_path=str(decrypted_path),
            error=str(exc),
        )
    return DecryptResult(
        decrypted=True,
        encrypted_path=str(encrypted_path),
        decrypted_path=str(decrypted_path),
    )


def verify_signed_mime(
    signed_path: str,
    *,
    account_email: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> str:
    _account, paths = require_configured(account_email)
    directory = Path(output_dir).expanduser() if output_dir else Path(signed_path).parent
    directory.mkdir(parents=True, exist_ok=True)
    verified_path = directory / "verified.eml"
    _run_openssl_file(
        [
            "smime",
            "-verify",
            "-in",
            str(Path(signed_path).expanduser()),
            "-CAfile",
            paths.ca_bundle,
            "-out",
            str(verified_path),
        ]
    )
    return str(verified_path)


def verify_signed_mime_bytes(
    mime_bytes: bytes,
    *,
    account_email: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> VerifyResult:
    _account, paths = require_configured(account_email)
    directory = Path(output_dir).expanduser() if output_dir else Path(tempfile.mkdtemp(prefix="msmail-smime-verify-"))
    directory.mkdir(parents=True, exist_ok=True)
    signed_path = directory / "incoming.eml"
    verified_path = directory / "verified.eml"
    signer_path = directory / "signer.pem"
    signed_path.write_bytes(mime_bytes)
    try:
        _run_openssl_file(
            [
                "smime",
                "-verify",
                "-in",
                str(signed_path),
                "-CAfile",
                paths.ca_bundle,
                "-signer",
                str(signer_path),
                "-out",
                str(verified_path),
            ]
        )
    except ValueError as exc:
        return VerifyResult(
            verified=False,
            signed=b"multipart/signed" in mime_bytes.lower()
            or b"application/pkcs7-signature" in mime_bytes.lower()
            or b"application/x-pkcs7-signature" in mime_bytes.lower(),
            verified_path=str(verified_path),
            signer_path=str(signer_path) if signer_path.exists() else None,
            error=str(exc),
        )

    signer_info = certificate_info(signer_path) if signer_path.exists() else None
    return VerifyResult(
        verified=True,
        signed=True,
        verified_path=str(verified_path),
        signer_path=str(signer_path) if signer_path.exists() else None,
        signer_certificate=signer_info,
    )


def local_sign_verify_smoke(
    *,
    account_email: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> LocalSignVerifyResult:
    account_email, _paths = require_configured(account_email)
    mime_bytes = build_text_mime(
        sender=account_email,
        to=[account_email],
        subject="msmail local S/MIME signing smoke",
        body="This is a local S/MIME signing and verification smoke test.",
    )
    unsigned_path, signed_path = sign_mime(
        mime_bytes,
        account_email=account_email,
        output_dir=output_dir,
    )
    verified_path = verify_signed_mime(
        signed_path,
        account_email=account_email,
        output_dir=output_dir,
    )
    return LocalSignVerifyResult(
        account=account_email,
        unsigned_path=unsigned_path,
        signed_path=signed_path,
        verified_path=verified_path,
        verified=True,
    )
