"""Audio device discovery and selection."""
import sounddevice as sd
import logging
from typing import List, Dict, Optional, Tuple
import sys

logger = logging.getLogger(__name__)


def list_devices() -> List[Dict]:
    """List all available audio devices with details."""
    devices = []
    hostapis = sd.query_hostapis()
    
    for i, device in enumerate(sd.query_devices()):
        hostapi = hostapis[device['hostapi']]
        devices.append({
            'index': i,
            'name': device['name'],
            'hostapi': hostapi['name'],
            'max_input_channels': device['max_input_channels'],
            'max_output_channels': device['max_output_channels'],
            'default_samplerate': device['default_samplerate'],
            'is_input': device['max_input_channels'] > 0,
            'is_output': device['max_output_channels'] > 0,
        })
    
    return devices


def find_device(
    name_substring: str = "",
    index_override: Optional[int] = None,
    is_input: bool = True
) -> Optional[int]:
    """
    Find audio device by substring match or explicit index.
    
    Args:
        name_substring: Substring to match in device name (case-insensitive)
        index_override: Explicit device index (takes precedence)
        is_input: True for input devices, False for output devices
    
    Returns:
        Device index or None if not found
    """
    if index_override is not None:
        try:
            device = sd.query_devices(index_override)
            has_channels = (
                device['max_input_channels'] > 0 if is_input
                else device['max_output_channels'] > 0
            )
            if has_channels:
                logger.info(
                    f"Using device index {index_override}: {device['name']}"
                )
                return index_override
            else:
                logger.warning(
                    f"Device index {index_override} does not have required channels"
                )
        except Exception as e:
            logger.error(f"Error accessing device index {index_override}: {e}")
            return None
    
    if not name_substring:
        # Use default device
        default_idx = sd.default.device[0 if is_input else 1]
        device = sd.query_devices(default_idx)
        logger.info(f"Using default device: {device['name']} (index {default_idx})")
        return default_idx
    
    devices = list_devices()
    name_lower = name_substring.lower()
    
    matches = []
    for device in devices:
        if is_input and device['max_input_channels'] == 0:
            continue
        if not is_input and device['max_output_channels'] == 0:
            continue
        
        if name_lower in device['name'].lower():
            matches.append(device)
    
    if not matches:
        logger.error(
            f"No {'input' if is_input else 'output'} device found matching "
            f"'{name_substring}'. Available devices:"
        )
        for device in devices:
            if (is_input and device['max_input_channels'] > 0) or \
               (not is_input and device['max_output_channels'] > 0):
                logger.error(f"  [{device['index']}] {device['name']}")
        return None
    
    if len(matches) > 1:
        logger.warning(
            f"Multiple devices match '{name_substring}'. Using first match."
        )
        for match in matches:
            logger.warning(f"  [{match['index']}] {match['name']}")
    
    selected = matches[0]
    logger.info(
        f"Selected {'input' if is_input else 'output'} device: "
        f"{selected['name']} (index {selected['index']})"
    )
    return selected['index']


def print_device_list() -> None:
    """Print formatted list of all audio devices."""
    devices = list_devices()
    
    print("\n=== INPUT DEVICES ===")
    for device in devices:
        if device['max_input_channels'] > 0:
            print(
                f"[{device['index']:3d}] {device['name']:<50} "
                f"({device['max_input_channels']} ch, "
                f"{device['default_samplerate']:.0f} Hz, "
                f"{device['hostapi']})"
            )
    
    print("\n=== OUTPUT DEVICES ===")
    for device in devices:
        if device['max_output_channels'] > 0:
            print(
                f"[{device['index']:3d}] {device['name']:<50} "
                f"({device['max_output_channels']} ch, "
                f"{device['default_samplerate']:.0f} Hz, "
                f"{device['hostapi']})"
            )
    
    print()


if __name__ == "__main__":
    # CLI mode: list devices
    print_device_list()

