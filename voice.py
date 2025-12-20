"""
Voice module for LocalAgent
Cross-platform STT (Whisper) and TTS (pyttsx3/edge-tts) support

Usage:
    interpreter --voice           # Enable voice input + output
    interpreter --voice-input     # Enable voice input only
    interpreter --voice-output    # Enable voice output only
"""

import os
import sys
import tempfile
import threading
import glob
import io

# Fix Windows console encoding for Chinese characters
if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except:
        pass

def _setup_ffmpeg_path(verbose=True):
    """Find and add ffmpeg to PATH if not already available"""
    # Check if ffmpeg is already in PATH
    import shutil
    if shutil.which("ffmpeg"):
        return True

    # Common ffmpeg locations on Windows
    home = os.path.expanduser("~")
    search_paths = [
        # WinGet installation
        os.path.join(home, "AppData", "Local", "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "ffmpeg-*", "bin"),
        # Chocolatey
        os.path.join("C:", os.sep, "ProgramData", "chocolatey", "lib", "ffmpeg", "tools", "ffmpeg", "bin"),
        # Scoop
        os.path.join(home, "scoop", "apps", "ffmpeg", "current", "bin"),
        # Common manual installations
        os.path.join("C:", os.sep, "ffmpeg", "bin"),
        os.path.join("C:", os.sep, "Program Files", "ffmpeg", "bin"),
    ]

    for pattern in search_paths:
        matches = glob.glob(pattern)
        for path in matches:
            ffmpeg_exe = os.path.join(path, "ffmpeg.exe")
            if os.path.exists(ffmpeg_exe):
                # Add to PATH
                os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")
                if verbose:
                    print(f"[Voice] Found ffmpeg at: {path}")
                return True

    return False

# Lazy imports to avoid loading heavy libraries when not needed
whisper_model = None
pyttsx_engine = None


class VoiceModule:
    """Cross-platform voice input/output for LocalAgent"""

    def __init__(self, language="auto", whisper_model_name="base", tts_engine="offline"):
        self.language = language
        self.whisper_model_name = whisper_model_name
        self.tts_engine = tts_engine  # "offline" or "edge"
        self._whisper_model = None
        self._pyttsx_engine = None
        self._initialized = False

        # Audio settings
        self.sample_rate = 16000
        self.silence_threshold = 0.01
        self.silence_duration = 1.5  # seconds
        self.max_record_duration = 30  # seconds
        self._stop_recording = False  # Flag for manual stop

    def _play_beep(self, frequency=800, duration=0.15, type="start"):
        """Play a beep sound for audio feedback"""
        try:
            import numpy as np
            import sounddevice as sd

            # Different tones for different events
            if type == "start":
                # Rising tone for start
                freq = 600
                duration = 0.1
            elif type == "stop":
                # Falling tone for stop
                freq = 400
                duration = 0.15
            elif type == "error":
                # Low tone for error
                freq = 300
                duration = 0.3
            else:
                freq = frequency

            t = np.linspace(0, duration, int(self.sample_rate * duration), False)
            tone = np.sin(2 * np.pi * freq * t) * 0.3  # 0.3 = volume

            # Add fade in/out to avoid clicks
            fade_len = int(self.sample_rate * 0.01)
            tone[:fade_len] *= np.linspace(0, 1, fade_len)
            tone[-fade_len:] *= np.linspace(1, 0, fade_len)

            sd.play(tone.astype(np.float32), self.sample_rate)
            sd.wait()
        except Exception:
            # If beep fails, just continue silently
            pass

    def initialize(self, verbose=True):
        """Initialize voice components (lazy loading)"""
        if self._initialized:
            return True

        try:
            # Check required libraries
            import numpy
            import sounddevice
            import soundfile
            if verbose:
                print("[Voice] Audio libraries loaded")

            # Initialize TTS
            if self.tts_engine == "offline":
                self._init_offline_tts(verbose=verbose)

            self._initialized = True
            return True
        except ImportError as e:
            print(f"[Voice] Missing dependency: {e}")
            print("[Voice] Install with: pip install sounddevice soundfile numpy")
            return False

    def _init_whisper(self, verbose=True):
        """Load Whisper model for STT (using faster-whisper)"""
        if self._whisper_model is not None:
            return True

        try:
            from faster_whisper import WhisperModel
            if verbose:
                print(f"[Voice] Loading faster-whisper model ({self.whisper_model_name})...")

            # Use CPU with int8 for better compatibility
            self._whisper_model = WhisperModel(
                self.whisper_model_name,
                device="cpu",
                compute_type="int8"
            )

            if verbose:
                print("[Voice] faster-whisper model loaded")
            return True
        except ImportError:
            print("[Voice] faster-whisper not installed. Install with: pip install faster-whisper")
            return False
        except Exception as e:
            print(f"[Voice] Failed to load Whisper: {e}")
            return False

    def _init_offline_tts(self, verbose=True):
        """Initialize pyttsx3 for offline TTS"""
        if self._pyttsx_engine is not None:
            return True

        try:
            import pyttsx3
            self._pyttsx_engine = pyttsx3.init()
            self._pyttsx_engine.setProperty('rate', 180)
            if verbose:
                print("[Voice] Offline TTS (pyttsx3) initialized")
            return True
        except ImportError:
            print("[Voice] pyttsx3 not installed. Install with: pip install pyttsx3")
            return False
        except Exception as e:
            print(f"[Voice] Failed to init TTS: {e}")
            return False

    def stop_recording(self):
        """Signal to stop recording manually"""
        self._stop_recording = True

    def record_audio(self, verbose=True):
        """Record audio from microphone, auto-stop on silence or manual stop"""
        import numpy as np
        import sounddevice as sd

        self._stop_recording = False  # Reset flag
        # Play start beep
        self._play_beep(type="start")
        if verbose:
            print("\n[Recording...] (speak now, stops on silence)")

        audio_chunks = []
        silence_samples = 0
        silence_threshold_samples = int(self.silence_duration * self.sample_rate)

        def callback(indata, frames, time, status):
            if status:
                print(f"[Recording status: {status}]")
            audio_chunks.append(indata.copy())

        try:
            with sd.InputStream(samplerate=self.sample_rate, channels=1,
                               dtype='float32', callback=callback):
                while True:
                    sd.sleep(100)  # 100ms

                    # Check for manual stop
                    if self._stop_recording:
                        self._play_beep(type="stop")
                        if verbose:
                            print("[Manual stop]")
                        break

                    if len(audio_chunks) > 0:
                        recent = audio_chunks[-1]
                        volume = np.abs(recent).mean()

                        if volume < self.silence_threshold:
                            silence_samples += len(recent)
                            if silence_samples >= silence_threshold_samples:
                                self._play_beep(type="stop")
                                if verbose:
                                    print("[Silence detected]")
                                break
                        else:
                            silence_samples = 0

                    # Max duration check
                    total = sum(len(c) for c in audio_chunks)
                    if total > self.sample_rate * self.max_record_duration:
                        self._play_beep(type="stop")
                        if verbose:
                            print("[Max duration reached]")
                        break

            if audio_chunks:
                return np.concatenate(audio_chunks, axis=0).flatten()
        except Exception:
            pass  # Silently ignore recording errors

        return None

    def transcribe(self, audio, verbose=True):
        """Convert audio to text using faster-whisper"""
        import numpy as np
        import soundfile as sf

        if audio is None or len(audio) == 0:
            return ""

        # Initialize Whisper on first use
        if not self._init_whisper(verbose=verbose):
            return ""

        if verbose:
            print("[Transcribing...]")

        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            sf.write(f.name, audio, self.sample_rate)
            temp_path = f.name

        try:
            # faster-whisper API: returns segments generator and info
            segments, info = self._whisper_model.transcribe(
                temp_path,
                language=self.language if self.language != "auto" else None,
                beam_size=5
            )
            # Collect all segments
            text = "".join([segment.text for segment in segments]).strip()
            return text
        except Exception as e:
            if verbose:
                print(f"[Voice] Transcription error: {e}")
            return ""
        finally:
            try:
                os.unlink(temp_path)
            except:
                pass

    def voice_input(self, verbose=True):
        """Record and transcribe voice input, return text

        Args:
            verbose: If True, print debug messages. If False, only return text.
        """
        if not self.initialize(verbose=verbose):
            return None

        audio = self.record_audio(verbose=verbose)
        if audio is None:
            return None

        text = self.transcribe(audio, verbose=verbose)
        if text and verbose:
            print(f"[You said]: {text}")
        return text

    def speak(self, text):
        """Convert text to speech and play"""
        if not text:
            return

        if self.tts_engine == "edge":
            self._speak_edge(text)
        else:
            self._speak_offline(text)

    def _speak_offline(self, text):
        """Speak using pyttsx3 (offline)"""
        if not self._init_offline_tts():
            return

        try:
            self._pyttsx_engine.say(text)
            self._pyttsx_engine.runAndWait()
        except Exception as e:
            print(f"[Voice] TTS error: {e}")

    def _speak_edge(self, text):
        """Speak using edge-tts (online)"""
        import asyncio

        async def _speak():
            try:
                import edge_tts
                import pygame

                # Select voice based on language
                voices = {
                    "zh": "zh-CN-XiaoxiaoNeural",
                    "en": "en-US-JennyNeural",
                    "ja": "ja-JP-NanamiNeural",
                }
                voice = voices.get(self.language, "zh-CN-XiaoxiaoNeural")

                # Generate audio
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                    temp_path = f.name

                communicate = edge_tts.Communicate(text, voice)
                await communicate.save(temp_path)

                # Play audio
                pygame.mixer.init()
                pygame.mixer.music.load(temp_path)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    pygame.time.Clock().tick(10)
                pygame.mixer.quit()

                os.unlink(temp_path)
            except ImportError as e:
                print(f"[Voice] edge-tts error: {e}")
                # Fallback to offline
                self._speak_offline(text)
            except Exception as e:
                print(f"[Voice] edge-tts error: {e}")

        try:
            asyncio.run(_speak())
        except:
            # Fallback to offline TTS
            self._speak_offline(text)

    def speak_async(self, text):
        """Speak in background thread"""
        thread = threading.Thread(target=self.speak, args=(text,), daemon=True)
        thread.start()
        return thread


# Global instance (lazy initialization)
_voice_module = None


def get_voice_module(language="auto", whisper_model="base", tts_engine="offline"):
    """Get or create voice module instance"""
    global _voice_module
    if _voice_module is None:
        _voice_module = VoiceModule(language, whisper_model, tts_engine)
    return _voice_module
