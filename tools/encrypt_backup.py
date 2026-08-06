from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Encrypt a verified MARK-OS backup with GnuPG before "
            "placing it in offsite storage."
        )
    )
    parser.add_argument("--backup", required=True)
    parser.add_argument("--output")
    parser.add_argument(
        "--recipient",
        help=(
            "Optional GPG recipient key ID/email for unattended "
            "public-key encryption. Without it, GPG prompts for a "
            "symmetric passphrase."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
    )
    return parser


def build_gpg_command(
    *,
    backup: Path,
    output: Path,
    recipient: str | None,
) -> list[str]:
    command = [
        "gpg",
        "--output",
        str(output),
    ]
    if recipient:
        command.extend(
            ["--encrypt", "--recipient", recipient]
        )
    else:
        command.extend(
            [
                "--symmetric",
                "--cipher-algo",
                "AES256",
                "--no-symkey-cache",
            ]
        )
    command.append(str(backup))
    return command


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    backup = Path(args.backup).expanduser().resolve()
    output = Path(
        args.output or f"{backup}.gpg"
    ).expanduser().resolve()

    if not backup.is_file():
        print(
            f"ERROR: backup file not found: {backup}",
            file=sys.stderr,
        )
        return 1
    if output.exists() and not args.overwrite:
        print(
            "ERROR: encrypted output already exists. Pass --overwrite "
            "only after confirming the destination.",
            file=sys.stderr,
        )
        return 1
    if shutil.which("gpg") is None:
        print(
            "ERROR: gpg is not installed. On macOS run: "
            "brew install gnupg",
            file=sys.stderr,
        )
        return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    command = build_gpg_command(
        backup=backup,
        output=output,
        recipient=args.recipient,
    )
    result = subprocess.run(command, check=False)
    if result.returncode != 0 or not output.is_file():
        output.unlink(missing_ok=True)
        print("ERROR: GPG encryption failed.", file=sys.stderr)
        return 1

    checksum = _sha256(output)
    checksum_path = output.with_suffix(output.suffix + ".sha256")
    checksum_path.write_text(
        f"{checksum}  {output.name}\n",
        encoding="utf-8",
    )

    print("Encrypted offsite backup created.")
    print(f"Encrypted file: {output}")
    print(f"Checksum file: {checksum_path}")
    print(f"SHA-256: {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
