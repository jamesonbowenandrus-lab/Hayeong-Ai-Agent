import whisper
from pathlib import Path

model = whisper.load_model("base")

audio_file = "voice_prep/samples/source_5secs.wav"

print(f"Transcribing {audio_file}...")
result = model.transcribe(
    audio_file, 
    language="en", 
    word_timestamps=True,
    initial_prompt="Include all filler words exactly as spoken, such as um, uh, like, you know, hmm, and any repeated words or false starts."
)

print("\n--- TRANSCRIPT ---\n")
print(result["text"])

output_file = Path(audio_file).stem + "_transcript.txt"
with open(output_file, "w") as f:
    f.write(result["text"])

print(f"\nSaved to: {output_file}")
