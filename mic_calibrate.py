# mic_calibrate.py
# Run this FIRST before main.py to figure out your mic's volume level.
# Usage: py mic_calibrate.py
import sounddevice as sd
import numpy as np
import time

SAMPLE_RATE = 16000

print("=" * 50)
print("  HAYEONG MIC CALIBRATION")
print("=" * 50)
print("\nAvailable audio devices:")
print(sd.query_devices())
print()

print("Listening for 15 seconds. Watch the volume bar.")
print("Stay SILENT for 3 seconds, then say 'Hayeong' a few times.\n")
print("You want SILENCE to be below your threshold, VOICE to be above it.\n")

silent_volumes = []
voice_volumes = []
phase = "silent"
start = time.time()

try:
    while True:
        elapsed = time.time() - start

        if elapsed < 3:
            phase = "SILENT (don't talk)"
        elif elapsed < 15:
            phase = "TALK — say 'Hayeong'!"
        else:
            break

        recording = sd.rec(int(0.5 * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1)
        sd.wait()
        vol = float(np.abs(recording).mean())

        if elapsed < 3:
            silent_volumes.append(vol)
        else:
            voice_volumes.append(vol)

        bar_len = int(vol * 3000)
        bar = "█" * min(bar_len, 50)
        print(f"  [{phase}]  vol={vol:.5f}  |{bar:<50}|", end="\r")

except KeyboardInterrupt:
    pass

print("\n\n" + "=" * 50)
if silent_volumes:
    print(f"  Silence average:  {np.mean(silent_volumes):.5f}")
    print(f"  Silence max:      {np.max(silent_volumes):.5f}")
if voice_volumes:
    print(f"  Voice average:    {np.mean(voice_volumes):.5f}")
    print(f"  Voice max:        {np.max(voice_volumes):.5f}")

if silent_volumes and voice_volumes:
    recommended = (np.max(silent_volumes) + np.mean(voice_volumes)) / 2
    print(f"\n  ✅ Recommended VOLUME_THRESHOLD: {recommended:.5f}")
    print(f"\n  Open voice.py and set:")
    print(f"    VOLUME_THRESHOLD = {recommended:.5f}")
else:
    print("\n  ⚠️  Couldn't get enough data. Try again and make sure your mic is working.")
    print("  If all volumes show 0.00000, your mic device may not be selected correctly.")
    print("  Run: py mic_test.py  to list all devices and find your mic's index.")
    print("  Then add this line at the top of voice.py:")
    print("    sd.default.device = X  # where X is your mic's input index")

print("=" * 50)
