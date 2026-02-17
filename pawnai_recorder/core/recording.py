"""Audio recording engine for PawnAI Recorder.

This module provides real-time audio capture capabilities with support for
multiple audio devices and formats.
"""

import datetime
import subprocess
import tempfile
from pathlib import Path
from threading import Thread
from typing import Optional

import numpy as np
import pyaudio
import soundfile as sf
from loguru import logger

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

from .config import RATE, CHUNK, CHANNEL, RECORDING_CHUNK_SIZE, FILE_EXTENSION, MP3_REQUIRED_RATE, MP3_REQUIRED_CHANNELS
from .processing import apply_gain, calculate_db_level


class RecordingEngine:
    """Real-time audio recording engine with device and format support."""

    @staticmethod
    def list_devices(driver_filter: Optional[str] = None) -> list:
        """List all available input audio devices.

        Args:
            driver_filter: Optional driver type to filter by ('pulse', 'alsa', 'jack', 'usb', 'default')

        Returns:
            List of device IDs that are input devices
        """
        from .processing import detect_driver_type

        audio = pyaudio.PyAudio()
        device_count = audio.get_device_count()
        default_device = audio.get_default_input_device_info()
        default_device_id = int(default_device['index']) if default_device else -1

        filter_text = f" (filtered by: {driver_filter})" if driver_filter else ""
        print(f"\nAvailable input devices{filter_text}:")
        print("-" * 80)
        input_devices = []

        for i in range(device_count):
            device_info = audio.get_device_info_by_index(i)
            if device_info.get('maxInputChannels', 0) > 0:
                device_name = device_info.get('name', 'Unknown')
                driver_type = detect_driver_type(device_name)

                # Skip if driver filter is specified and doesn't match
                if driver_filter and driver_type != driver_filter.lower():
                    continue

                input_devices.append(i)
                channels = device_info.get('maxInputChannels', 0)
                sample_rate = int(device_info.get('defaultSampleRate', 0))
                default = " [DEFAULT]" if i == default_device_id else ""
                print(f"{i}: {device_name}")
                print(f"   Driver: {driver_type.upper()} | Channels: {channels} | Sample Rate: {sample_rate} Hz{default}")

        audio.terminate()
        print("-" * 80 + "\n")
        return input_devices


class MicrophoneStream:
    """Opens a recording stream as a generator yielding the audio chunks."""

    def __init__(
        self,
        rate: int = RATE,
        chunk: int = CHUNK,
        output_dir: str = "audio/",
        chunk_size: int = RECORDING_CHUNK_SIZE,
        device_id: Optional[int] = None,
        show_level_meter: bool = True,
        gain_factor: float = 1.0,
        file_format: str = FILE_EXTENSION,
    ) -> None:
        """Initialize the microphone stream.

        Args:
            rate: Sample rate in Hz
            chunk: Chunk size in samples
            output_dir: Output directory for recordings
            chunk_size: Number of frames per chunk
            device_id: Audio device ID to use
            show_level_meter: Whether to show level meter
            gain_factor: Input gain factor
            file_format: Audio format (flac, ogg, wav, mp3, etc.)

        Raises:
            ValueError: If MP3 format is requested with invalid sample rate or channels
        """
        # Validate MP3 format requirements
        if file_format.lower() == 'mp3':
            if rate != MP3_REQUIRED_RATE:
                raise ValueError(
                    f"MP3 format requires {MP3_REQUIRED_RATE}Hz sample rate, got {rate}Hz"
                )
            if CHANNEL != MP3_REQUIRED_CHANNELS:
                raise ValueError(
                    f"MP3 format requires {MP3_REQUIRED_CHANNELS} channel (mono), got {CHANNEL}"
                )

        self._rate = rate
        self._chunk = chunk
        self._channel = CHANNEL
        self._sample_width = pyaudio.paInt16
        self._output_dir = output_dir
        self._chunk_size = chunk_size
        self._device_id = device_id
        self._show_level_meter = show_level_meter
        self._gain_factor = gain_factor
        self._file_format = file_format
        self._current_db_level = 0

        self._audio_interface = None
        self._audio_stream = None

        self._recording_frames = []
        self._count = 0
        self._session_id = datetime.datetime.now().strftime('%y%m%d%H%M%S')

        # Create output directory if it doesn't exist
        Path(self._output_dir).mkdir(parents=True, exist_ok=True)

    def start_recording(self) -> None:
        """Start the recording stream."""
        self._audio_interface = pyaudio.PyAudio()

        # Get device info and use its native sample rate
        device_info = self._audio_interface.get_device_info_by_index(self._device_id)
        device_sample_rate = int(device_info.get('defaultSampleRate', self._rate))
        device_name = device_info.get('name', 'Unknown')

        # Update the rate to match device's native rate
        self._rate = device_sample_rate

        self._audio_stream = self._audio_interface.open(
            format=self._sample_width,
            channels=self._channel,
            rate=self._rate,
            input=True,
            input_device_index=self._device_id,
            frames_per_buffer=self._chunk,
            stream_callback=self._fill_buffer,
        )
        logger.info(f'Recording started. Session ID: {self._session_id}')
        logger.info(f'Device: {device_name} (ID: {self._device_id})')
        logger.info(f'Sample Rate: {self._rate} Hz')
        logger.info(f'Output directory: {self._output_dir}')

    def stop_recording(self) -> None:
        """Close the recording stream and save any remaining frames."""
        if self._audio_stream:
            self._audio_stream.stop_stream()
            self._audio_stream.close()
        if self._audio_interface:
            self._audio_interface.terminate()

        if self._recording_frames:
            saving_frames = self._recording_frames[:]
            self._recording_frames = []
            self._count += 1

            self._create_chunk_saving_thread(saving_frames, self._count)

        logger.info('Microphone has been closed')

    def _fill_buffer(
        self,
        in_data: bytes,
        frame_count: int,
        time_info: object,
        status_flags: object,
    ) -> tuple:
        """Continuously collect data from the audio stream into the buffer.

        Args:
            in_data: The audio data as a bytes object
            frame_count: The number of frames captured
            time_info: The time information
            status_flags: The status flags

        Returns:
            Tuple of (data, status_flag)
        """
        # Apply gain to audio data
        processed_data = apply_gain(in_data, self._gain_factor)

        # Calculate and update dB level for display (on processed data)
        if self._show_level_meter:
            self._current_db_level = calculate_db_level(processed_data, sample_width=2)

        self._recording_frames.append(processed_data)
        if len(self._recording_frames) >= self._chunk_size:
            saving_frames = self._recording_frames[:]
            self._recording_frames = []
            self._count += 1

            self._create_chunk_saving_thread(saving_frames, self._count)

        return None, pyaudio.paContinue

    def get_current_db_level(self) -> float:
        """Get the current dB level.

        Returns:
            Current dB level
        """
        return self._current_db_level

    def _create_chunk_saving_thread(self, saving_frames, count):
        """Create a thread to save audio chunk asynchronously.

        Args:
            saving_frames: Frames to save
            count: Chunk count
        """
        created_at = datetime.datetime.now().strftime('%y%m%d%H%M%S')

        saving_thread = Thread(
            target=self._save,
            args=(saving_frames, count, created_at,),
            daemon=True,
        )
        saving_thread.start()
        logger.info(f'Saving chunk {count} (session: {self._session_id})')

    def _save(self, frames, count, start_time):
        """Save audio frames to file.

        Args:
            frames: List of audio frames
            count: Chunk number
            start_time: Start timestamp
        """
        # Ensure output directory has trailing slash
        output_dir = self._output_dir if self._output_dir.endswith('/') else self._output_dir + '/'
        filename = f'{output_dir}{self._session_id}_{count:02}.{self._file_format}'
        
        try:
            # Convert byte frames to numpy audio array
            audio_data = np.frombuffer(b''.join(frames), dtype=np.int16)

            if self._file_format.lower() == 'mp3':
                # Save MP3 format
                self._save_mp3(filename, audio_data)
            else:
                # Normalize to float32 for soundfile (-1.0 to 1.0 range)
                audio_data = audio_data.astype(np.float32) / 32768.0

                # Write with soundfile (supports FLAC, OGG, WAV, etc.)
                sf.write(filename, audio_data, self._rate, subtype='PCM_16')
            
            logger.info(f'Saved: {filename} ({len(frames)} frames)')
        except Exception as e:
            logger.error(f'Error saving {filename}: {e}')

    def _save_mp3(self, filename: str, audio_data: np.ndarray) -> None:
        """Save audio data as MP3 file.

        Args:
            filename: Output MP3 file path
            audio_data: Audio data as int16 numpy array

        Raises:
            RuntimeError: If MP3 encoding fails
        """
        if PYDUB_AVAILABLE:
            # Use pydub if available
            try:
                audio_segment = AudioSegment(
                    data=audio_data.tobytes(),
                    sample_width=2,  # 16-bit = 2 bytes
                    frame_rate=self._rate,
                    channels=self._channel
                )
                audio_segment.export(filename, format="mp3", bitrate="192k")
                return
            except Exception as e:
                logger.debug(f"Pydub MP3 encoding failed, trying ffmpeg: {e}")

        # Fallback: Use ffmpeg command line
        try:
            self._save_mp3_with_ffmpeg(filename, audio_data)
        except Exception as e:
            logger.error(f"MP3 encoding failed: {e}")
            raise

    def _save_mp3_with_ffmpeg(self, filename: str, audio_data: np.ndarray) -> None:
        """Save audio data as MP3 using ffmpeg command line.

        Args:
            filename: Output MP3 file path
            audio_data: Audio data as int16 numpy array

        Raises:
            RuntimeError: If ffmpeg is not available or encoding fails
        """
        # Create a temporary WAV file
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            tmp_wav = tmp.name
            # Normalize to float32 for soundfile
            audio_float = audio_data.astype(np.float32) / 32768.0
            sf.write(tmp_wav, audio_float, self._rate, subtype='PCM_16')

        try:
            # Ensure output directory exists
            output_path = Path(filename)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Use ffmpeg to convert WAV to MP3
            cmd = [
                'ffmpeg',
                '-i', tmp_wav,
                '-codec:a', 'libmp3lame',
                '-b:a', '192k',
                '-y',  # Overwrite output file without asking
                filename
            ]
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.debug(f"ffmpeg encoding complete for {filename}")
        except FileNotFoundError:
            raise RuntimeError(
                "MP3 encoding requires either 'pydub' package or 'ffmpeg' command line tool. "
                "Install with: pip install pydub or apt-get install ffmpeg"
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"ffmpeg stderr: {e.stderr}")
            raise RuntimeError(f"ffmpeg MP3 encoding failed: {e.stderr}")
        finally:
            # Clean up temporary WAV file
            try:
                Path(tmp_wav).unlink()
            except Exception as e:
                logger.debug(f"Error cleaning up temp file {tmp_wav}: {e}")
