# Recorded interview observation setup

The head-orientation and speaker observations are optional, score-independent
backend processing. Missing models produce explicit `model_unavailable` results;
they do not remove transcripts, video playback, or answer scores.

## Python and packages

The dependency set resolves for CPython 3.13 on Windows. A separate Python 3.11
worker is not required. A project virtual environment is recommended because
PyTorch and pyannote are large dependencies:

```powershell
cd C:\Users\VedaiSOFT\recruitment-ai\backend
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

FFmpeg must remain available on `PATH`. The analyzer invokes it only after a
recording has been uploaded and stored.

## MediaPipe Face Landmarker

The implementation uses the MediaPipe Tasks Face Landmarker in VIDEO mode. It
requires the official task model, which is deliberately excluded from Git.

```powershell
New-Item -ItemType Directory -Force .\models\mediapipe
Invoke-WebRequest `
  -Uri "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task" `
  -OutFile ".\models\mediapipe\face_landmarker.task"
```

Set this in `backend/.env` (the path is resolved from the repository root):

```dotenv
FACE_LANDMARKER_MODEL_PATH=backend/models/mediapipe/face_landmarker.task
```

Do not add the `.task` binary to Git.

## pyannote Community-1 diarisation

1. Sign in to Hugging Face.
2. Visit https://huggingface.co/pyannote/speaker-diarization-community-1
   and accept the model access conditions.
3. Create a read-only token at https://huggingface.co/settings/tokens.
4. Store it only in `backend/.env`:

```dotenv
HUGGINGFACE_TOKEN=your_backend_only_read_token
SPEAKER_DIARIZATION_MODEL=pyannote/speaker-diarization-community-1
SPEAKER_DIARIZATION_DEVICE=cpu
```

The first configured run downloads model weights to the Hugging Face cache.
The token is never returned to or used by the frontend and is not logged.
Community-1 is subject to its Hugging Face access conditions and CC-BY-4.0
model licence. `pyannote.audio` source code is MIT licensed.

The analyzer passes the FFmpeg-normalized PCM samples to pyannote as an
in-memory waveform. This deliberately avoids TorchCodec's shared-FFmpeg DLL
requirement on Windows; no candidate voiceprint or permanent speaker embedding
is created or stored.

Set `SPEAKER_DIARIZATION_DEVICE=cuda` only on a host with a compatible CUDA
PyTorch installation. CPU is the safe Windows default.

## Threshold rationale

All thresholds are centralized in `ObservationConfig` and may be overridden in
`backend/.env`. Sampling at 2 FPS limits CPU use while retaining half-second
interval boundaries. A 2-second consecutive interval is required for downward
orientation or face absence so brief natural movement is not described as
sustained. Rapid movement defaults to a conservative 40-degree change within
0.75 seconds. At least five clear face frames and 30% face coverage are required
before orientation summaries are reported. Speaker labels must persist for at
least 1.5 seconds, individual segments under 0.5 seconds are discarded, and at
least 2 seconds of speech is required. These are operational starting points,
not validated behavioural or suitability measures, and should be tuned only
against consented recordings representative of the deployment environment.

## Verification

Restart FastAPI after installing packages or changing model configuration. Its
startup log reports only package/model/token availability states, never token
contents. Analyze one stored recording with:

```powershell
.\.venv\Scripts\python.exe analyze_recording.py "media\interviews\<interview-id>\0.webm"
```

The script prints aggregate observations only. It does not print frames,
landmarks, transcripts, speaker embeddings, or tokens.
