"""Deterministic runtime-platform capabilities and routing policy hints."""
from dataclasses import dataclass
from enum import Enum
import platform as stdlib_platform
from typing import Optional


class OperatingSystem(str, Enum):
    """Operating systems recognized by the application."""

    MACOS = "macos"
    WINDOWS = "windows"
    LINUX = "linux"
    OTHER = "other"


@dataclass(frozen=True)
class RuntimePlatform:
    """Small, injectable set of platform facts used by backend selection."""

    operating_system: OperatingSystem
    machine: str

    @classmethod
    def detect(cls) -> "RuntimePlatform":
        """Detect the current platform through Python's standard library."""
        return cls.from_values(stdlib_platform.system(), stdlib_platform.machine())

    @classmethod
    def from_values(cls, system: str, machine: str) -> "RuntimePlatform":
        """Build normalized platform facts from deterministic input values."""
        normalized_system = system.strip().lower()
        operating_system = {
            "darwin": OperatingSystem.MACOS,
            "windows": OperatingSystem.WINDOWS,
            "linux": OperatingSystem.LINUX,
        }.get(normalized_system, OperatingSystem.OTHER)
        return cls(operating_system=operating_system, machine=machine.strip().lower())

    @property
    def is_apple_silicon(self) -> bool:
        """Whether this is macOS running on an ARM64 Apple Silicon CPU."""
        return (
            self.operating_system is OperatingSystem.MACOS
            and self.machine in {"arm64", "aarch64"}
        )

    @property
    def supports_sapi(self) -> bool:
        """Whether Windows SAPI is a valid platform capability."""
        return self.operating_system is OperatingSystem.WINDOWS

    @property
    def cuda_configuration_relevant(self) -> bool:
        """Whether CUDA configuration can be relevant, not whether CUDA exists."""
        return self.operating_system in {
            OperatingSystem.WINDOWS,
            OperatingSystem.LINUX,
        }

    @property
    def virtual_audio_routing(self) -> Optional[str]:
        """Return the expected virtual-audio family without overriding config."""
        if self.operating_system is OperatingSystem.WINDOWS:
            return "vb-cable"
        if self.operating_system is OperatingSystem.MACOS:
            return "blackhole"
        return None
