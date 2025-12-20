# Io Pet - Desktop Companion

A cute desktop pet with AI chat capabilities, powered by LocalAgent.

## Features

- Desktop pet UI (glowing orb with breathing animation)
- Voice input (Whisper STT) and output (Edge TTS)
- Smart routing: Chat mode (fast) vs Agent mode (code execution)
- Code execution confirmation before running
- Cross-platform: Windows & Linux

## Requirements

- Python 3.10+
- [LocalAgent](https://github.com/Crows12138/LocalAgent) running on port 8000
- [Ollama](https://ollama.ai) with `qwen2.5:1.5b` model

## Installation

```bash
# Clone
git clone https://github.com/Crows12138/IoPet.git
cd IoPet

# Install dependencies
pip install -r requirements.txt

# Linux: install audio dependencies
# Ubuntu/Debian:
sudo apt install portaudio19-dev ffmpeg

# Arch:
sudo pacman -S portaudio ffmpeg
```

## Usage

```bash
# 1. Start Ollama
ollama serve

# 2. Start LocalAgent (in another terminal)
cd /path/to/LocalAgent
python api_server.py

# 3. Start Io Pet
python io_pet.py
```

## Platform Notes

| Feature | Windows | Linux |
|---------|---------|-------|
| Desktop Pet UI | ✅ | ✅ |
| Voice Input/Output | ✅ | ✅ |
| Window Context Tracking | ✅ | ❌ (planned) |
| System Tray | ✅ | ✅ |

## License

MIT
