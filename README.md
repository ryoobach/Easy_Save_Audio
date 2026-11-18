# Easy Save Audio & Video 2.0

Windows 64-bit portable multimedia utility.

## Current 2.0 foundation

- Separate **MP3 다운로드** and **동영상 다운로드** tabs
- URL-based MP3 extraction and video download using yt-dlp and FFmpeg
- Optional MP3 + video output from one URL
- Local audio/video file selection and batch registration
- Local file drag-and-drop with automatic MP3 extraction staging
- Browser URL drag-and-drop checkbox (URL text payloads supported)
- Explicit [변환 시작] control; new inputs are staged, not auto-run
- Two concurrent background jobs with per-job status and progress
- Remember separate MP3 and video output folders
- Preserve and migrate the existing 1.x settings/history file
- App title and initial screen show the current version
- App information shows only product name, version, and Windows platform

## Build

The existing GitHub Actions workflow builds the Windows x64 portable executable.

Artifact: `Easy-Save-Audio-Video-Windows-x64`

Executable: `EasySaveAudioVideo.exe`

## Notes

- Existing repository and GitHub Actions workflow are retained.
- The previous `main.py` remains in the repository as the 1.x implementation; the 2.0 workflow builds `app_v2.py`.
- A full browser extension/native-messaging bridge is not included; browser URL drag-and-drop works when the browser exposes a URL text payload to Windows drag-and-drop.
- Use only media and URLs that you are authorized to download. DRM and access-control circumvention are not supported.
