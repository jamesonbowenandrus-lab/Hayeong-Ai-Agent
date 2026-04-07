import re

file = r"H:\hayeong\.venv\Lib\site-packages\torchaudio\__init__.py"

with open(file, "r", encoding="utf-8") as f:
    content = f.read()

new_load = '''def load(
    uri,
    frame_offset: int = 0,
    num_frames: int = -1,
    normalize: bool = True,
    channels_first: bool = True,
    format=None,
    buffer_size: int = 4096,
    backend=None,
):
    """Patched load() using soundfile - torchcodec not available on ROCm."""
    import soundfile as sf
    import torch
    data, sample_rate = sf.read(uri, dtype="float32", always_2d=True)
    if frame_offset > 0:
        data = data[frame_offset:]
    if num_frames > 0:
        data = data[:num_frames]
    tensor = torch.from_numpy(data)
    if channels_first:
        tensor = tensor.T  # [channels, time]
    return tensor, sample_rate
'''

# Replace the entire load function
content = re.sub(r'def load\(.*?return load_with_torchcodec\(.*?\n    \)', new_load, content, flags=re.DOTALL)

with open(file, "w", encoding="utf-8") as f:
    f.write(content)

print("Done! Patched torchaudio load() to use soundfile.")