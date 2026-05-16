from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Iterable, Sequence


DEFAULT_CHATGPT_URL = "https://chatgpt.com/"
DEFAULT_WAIT_SECONDS = 3.0
DEFAULT_IMAGE_SETTLE_SECONDS = 3.0
DEFAULT_FINAL_SETTLE_SECONDS = 6.0
DEFAULT_SUBMIT_ATTEMPTS = 6
DEFAULT_SUBMIT_RETRY_SECONDS = 2.0


class ChatGPTWebError(RuntimeError):
    """Raised when ChatGPT foreground browser automation fails."""


def _require_macos_command(command: str) -> None:
    if platform.system() != "Darwin":
        raise ChatGPTWebError("ChatGPT web automation currently requires macOS")
    if shutil.which(command) is None:
        raise ChatGPTWebError(f"required macOS command not found: {command}")


def _run(command: Sequence[str], *, input_text: str | None = None) -> None:
    try:
        subprocess.run(
            command,
            input=input_text,
            text=input_text is not None,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr
        raise ChatGPTWebError(
            f"{command[0]} failed with exit code {exc.returncode}: {stderr.strip()}"
        ) from exc


def _osascript(script: str) -> None:
    _run(["osascript", "-e", script])


def _applescript_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _validate_image_paths(image_paths: Iterable[Path | str]) -> list[Path]:
    resolved: list[Path] = []
    for image_path in image_paths:
        path = Path(image_path).expanduser().resolve()
        if not path.is_file():
            raise ChatGPTWebError(f"image path does not exist: {path}")
        resolved.append(path)
    return resolved


def _clipboard_image_script(path: Path) -> str:
    path_literal = _applescript_string(str(path))
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return (
            f"set the clipboard to (read (POSIX file {path_literal} as alias) "
            "as «class JPEG»)"
        )
    if suffix == ".png":
        return (
            f"set the clipboard to (read (POSIX file {path_literal} as alias) "
            "as «class PNGf»)"
        )
    raise ChatGPTWebError(f"unsupported clipboard image format: {path.suffix}")


def _prepare_clipboard_image(path: Path, temp_dir: Path) -> Path:
    if path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        return path

    _require_macos_command("sips")
    converted = temp_dir / f"{path.stem}.png"
    _run(["sips", "-s", "format", "png", str(path), "--out", str(converted)])
    if not converted.is_file():
        raise ChatGPTWebError(f"failed to convert image for clipboard: {path}")
    return converted


def _paste_file(path: Path, *, settle_seconds: float) -> None:
    # ChatGPT handles pasted image data more reliably than Finder-style file
    # aliases, so put actual PNG/JPEG data on the clipboard before Cmd+V.
    script = f"""
{_clipboard_image_script(path)}
tell application "System Events"
    delay 0.2
    keystroke "v" using {{command down}}
    delay {settle_seconds}
end tell
"""
    _osascript(script)


def _paste_prompt(
    prompt: str,
    *,
    submit: bool,
    final_settle_seconds: float,
    submit_attempts: int,
    submit_retry_seconds: float,
) -> None:
    _run(["pbcopy"], input_text=prompt)
    submit_script = """
tell application "System Events"
    delay 0.3
    keystroke "v" using {command down}
"""
    if submit:
        submit_script += f"""    delay {final_settle_seconds}
    repeat {submit_attempts} times
        key code 36
        delay 0.4
        key code 36 using {{command down}}
        delay {submit_retry_seconds}
    end repeat
"""
    submit_script += "end tell\n"
    _osascript(submit_script)


def send_to_chatgpt(
    prompt: str,
    image_paths: Iterable[Path | str] = (),
    *,
    url: str = DEFAULT_CHATGPT_URL,
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
    image_settle_seconds: float = DEFAULT_IMAGE_SETTLE_SECONDS,
    final_settle_seconds: float = DEFAULT_FINAL_SETTLE_SECONDS,
    submit_attempts: int = DEFAULT_SUBMIT_ATTEMPTS,
    submit_retry_seconds: float = DEFAULT_SUBMIT_RETRY_SECONDS,
    submit: bool = True,
) -> None:
    """Open ChatGPT web, upload image files, paste a prompt, and optionally submit.

    This intentionally uses foreground browser automation and the user's existing
    ChatGPT login. The caller must keep the browser focused while the automation
    runs, and macOS must grant Accessibility permission to the launching app.
    """
    if not prompt.strip():
        raise ChatGPTWebError("prompt cannot be empty")

    for command in ("open", "pbcopy", "osascript"):
        _require_macos_command(command)

    images = _validate_image_paths(image_paths)

    _run(["open", url])
    time.sleep(wait_seconds)

    with tempfile.TemporaryDirectory(prefix="chatgpt-web-images-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        for image in images:
            clipboard_image = _prepare_clipboard_image(image, temp_dir)
            _paste_file(clipboard_image, settle_seconds=image_settle_seconds)

        _paste_prompt(
            prompt,
            submit=submit,
            final_settle_seconds=final_settle_seconds,
            submit_attempts=submit_attempts,
            submit_retry_seconds=submit_retry_seconds,
        )


def _read_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).expanduser().read_text(encoding="utf-8")
    if args.prompt:
        return " ".join(args.prompt)
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise ChatGPTWebError("provide prompt text, --prompt-file, or stdin")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Open ChatGPT web, upload optional images, paste a prompt, and submit."
    )
    parser.add_argument("prompt", nargs="*", help="Prompt text to send")
    parser.add_argument(
        "--image",
        action="append",
        default=[],
        dest="images",
        help="Image path to upload before the prompt. May be repeated.",
    )
    parser.add_argument("--prompt-file", help="Read prompt text from this file")
    parser.add_argument("--url", default=DEFAULT_CHATGPT_URL)
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=DEFAULT_WAIT_SECONDS,
        help="Seconds to wait after opening ChatGPT before pasting.",
    )
    parser.add_argument(
        "--image-settle-seconds",
        type=float,
        default=DEFAULT_IMAGE_SETTLE_SECONDS,
        help="Seconds to wait after each image paste.",
    )
    parser.add_argument(
        "--final-settle-seconds",
        type=float,
        default=DEFAULT_FINAL_SETTLE_SECONDS,
        help="Seconds to wait after prompt paste before submitting.",
    )
    parser.add_argument(
        "--submit-attempts",
        type=int,
        default=DEFAULT_SUBMIT_ATTEMPTS,
        help="Number of Enter/Cmd+Enter submit attempts.",
    )
    parser.add_argument(
        "--submit-retry-seconds",
        type=float,
        default=DEFAULT_SUBMIT_RETRY_SECONDS,
        help="Seconds to wait between submit attempts.",
    )
    parser.add_argument(
        "--no-submit",
        action="store_true",
        help="Paste images and prompt but do not press Return.",
    )

    args = parser.parse_args(argv)
    try:
        prompt = _read_prompt(args)
        send_to_chatgpt(
            prompt,
            args.images,
            url=args.url,
            wait_seconds=args.wait_seconds,
            image_settle_seconds=args.image_settle_seconds,
            final_settle_seconds=args.final_settle_seconds,
            submit_attempts=args.submit_attempts,
            submit_retry_seconds=args.submit_retry_seconds,
            submit=not args.no_submit,
        )
    except ChatGPTWebError as exc:
        print(f"chatgpt_web: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
