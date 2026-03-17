import soundfile as sf
from f5_tts.api import F5TTS
from pathlib import Path

tts = F5TTS()

ref_audio = "voice_prep/samples/source_5secs.wav"
ref_text = "Before the video starts, I want to make a quick announcement."

test_lines = [
    "I was just wondering what you thought about that.",
    "Hey, what were you planning to do?",
    "Like, what's on your schedule today?",
    "Is there something I can help you with?",
]

print(f"Using reference: {ref_audio}")
print("Generating... this might take a minute")

for i, line in enumerate(test_lines):
    print(f"Generating chunk {i+1}...")
    wav, sr, _ = tts.infer(
        ref_file=ref_audio,
        ref_text=ref_text,
        gen_text=line,
        nfe_step=64,
        speed=1.0,
    )
    print(f"wav type: {type(wav)}, shape: {wav.shape if hasattr(wav, 'shape') else len(wav)}, sr: {sr}")
    filename = f"f5_chunk_{i+1}.wav"
    sf.write(filename, wav, sr)
    print(f"Saved: {filename}")
    
print("Done. Listen to each chunk separately.")