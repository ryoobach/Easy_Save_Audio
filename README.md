# Easy Save Audio & Video 2.0

Windows 64-bit portable multimedia utility.

## Current 2.0 foundation

- Separate **MP3 다운로드** and **동영상 다운로드** tabs
- URL-based MP3 extraction and video download using yt-dlp and FFmpeg
- Optional MP3 + video output from one URL
- Local audio/video file selection and batch registration
- Optional Windows drag-and-drop file input
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
- Browser extension/native messaging, broader media-format conversion, persistent resumable queue state, and the remaining planned refinements are subsequent development work.
- Use only media and URLs that you are authorized to download. DRM and access-control circumvention are not supported.
