from __future__ import annotations

from types import SimpleNamespace
from typing import BinaryIO


class Magika:
    """Small MarkItDown-compatible classifier shim for Alpine add-on images.

    MarkItDown uses Magika to refine MIME guesses, but Magika depends on
    onnxruntime, which is not available for musllinux/aarch64 in Home Assistant's
    Alpine base image. Returning "unknown" makes MarkItDown fall back to the
    extension and MIME hints we preserve on uploaded temp files.
    """

    def identify_stream(self, _file_stream: BinaryIO) -> SimpleNamespace:
        return SimpleNamespace(
            status="ok",
            prediction=SimpleNamespace(
                output=SimpleNamespace(label="unknown"),
            ),
        )
