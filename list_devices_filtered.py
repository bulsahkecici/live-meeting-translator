import sounddevice as sd
import sys

# Set stdout to utf-8
sys.stdout.reconfigure(encoding='utf-8')

print("--- Audio Devices ---")
try:
    devices = sd.query_devices()
    for i, dev in enumerate(devices):
        name = dev.get('name', '')
        # Filter for relevant devices
        if any(x in name for x in ['CABLE', 'Mix', 'Speaker', 'Hoparlör', 'Mikrofon', 'Mic']):
            print(f"Index {i}: {name} (In: {dev['max_input_channels']}, Out: {dev['max_output_channels']})")
except Exception as e:
    print(f"Error: {e}")
