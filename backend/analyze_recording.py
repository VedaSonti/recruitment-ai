"""Print neutral aggregate observations for one locally stored WebM."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze one recorded interview WebM without printing private media data."
    )
    parser.add_argument("video", help="Path to a saved WebM recording")
    args = parser.parse_args()

    backend_dir = Path(__file__).resolve().parent
    load_dotenv(backend_dir / ".env")

    video_path = Path(args.video)
    if not video_path.is_absolute():
        video_path = (Path.cwd() / video_path).resolve()
    if not video_path.is_file():
        parser.error("The recording does not exist or is not a file.")

    # Import after loading backend configuration.
    from recording_observations import analyze_recording

    observations = analyze_recording(str(video_path))
    print(json.dumps(observations, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
