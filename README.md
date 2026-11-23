# Easy Save Audio & Video

**현재 소스 버전: v2.3.9 (개발 정리 빌드)**  
Windows 64-bit portable multimedia utility.

## 현재 작업 기준

- MP3 변환 호환성 테스트를 위한 10개 프로필 실행파일(J–S)을 한 패키지로 생성합니다.
- 실행파일 10개는 공용 `_internal` 런타임 폴더를 사용합니다.
- MP3 인코딩은 PCM WAV 중간 파일을 거쳐 독립 실행형 LAME를 호출합니다.
- FFmpeg/FFprobe는 디코딩, 미디어 정보 확인 및 진단에 사용합니다.
- 현재 인터페이스는 유지합니다. 사용자가 요청하지 않는 한 UI/레이아웃을 변경하지 않습니다.
- **Winamp 실제 재생 호환성 문제는 아직 해결되지 않았습니다.** 기술적 파일 검사 통과만으로 Winamp 재생 성공으로 판정하지 않습니다.

## 버전 2.3.9 변경

- 앱 진단 로그를 재실행 시 초기화하지 않고 세션 간 계속 누적하도록 변경합니다.
- 로그 자동 삭제/순환/크기 제한을 두지 않습니다.
- MP3 인코딩 방식과 UI는 변경하지 않았습니다.
- 이 버전의 Windows 10개 실행파일 빌드 및 Winamp 재생 테스트는 아직 수행 전입니다.

## 빌드

GitHub Actions의 `Build Easy Save Audio & Video (Windows x64)` 워크플로가 Windows x64 패키지를 생성합니다.

- 프로필 실행파일: `EasySave_J.exe` ~ `EasySave_S.exe`
- 공용 런타임: `_internal/`
- 산출물 이름: `Easy-Save-Audio-Video-v2.3.9-Winamp10-LAME-Windows-x64`

## 저장소 안내

- [개발·빌드 이력 및 재작업 방지 장부](DEVELOPMENT_LOG.md)
- [문서/버전 설명서 색인](docs/README.md)
- [v2.3.9 기능 설명서](docs/releases/Easy_Save_Audio_Video_기능설명서_v2.3.9.md)
- [11월 22일 MP3 테스트 회고](docs/2026-11-22_test-retrospective.md)
- [MP3 테스트 원본/대조 파일](tests/fixtures/audio/)

## 소스 구조

- `app_v2.py`: 현재 2.x 앱
- `main.py`: 기존 1.x 구현 보존
- `browser_extension/`: 브라우저 확장 프로그램 소스
- `browser_extension_installer.py`: 확장 프로그램 설치 도우미
- `make_icon.py`: 앱 아이콘 생성
- `requirements.txt`: Python 의존성
- `.github/workflows/build-windows.yml`: Windows 10개 프로필 빌드

## 진단 로그

앱의 `diagnostic.log`는 사용자 AppData의 EasySaveAudio 폴더에 저장됩니다. 앱을 다시 실행해도 기존 기록을 지우지 않고 계속 누적합니다. 자동 순환/삭제/크기 제한은 두지 않습니다. 디스크 공간 부족 등 운영체제 한계는 적용됩니다.

## 다운로드 및 저작권

사용 권한이 있는 미디어와 URL만 다운로드하십시오. DRM 및 접근 제어 우회는 지원하지 않습니다.
