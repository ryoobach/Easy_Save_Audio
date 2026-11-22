# Easy Save Audio & Video 기능 설명서 v2.3.8

## 1. 이번 빌드의 핵심 변경
- MP3 인코딩을 FFmpeg 내부 `libmp3lame` 호출에서 **독립 실행형 LAME 4.0 `lame.exe`** 직접 실행 방식으로 변경했습니다.
- FFmpeg는 원본 오디오를 PCM WAV로 디코딩하고 필요한 음량 정규화를 적용하는 데 사용합니다.
- 독립 실행형 LAME가 WAV를 MP3로 인코딩합니다.
- 실행 파일 10개는 각각 하나의 호환성 프로필을 포함합니다.
- LAME는 ASCII 전용 임시 경로에 MP3를 생성한 뒤, 앱이 원래 한글·이모지 파일명으로 이동합니다. 최종 파일명과 ID3 제목은 원래 제목을 유지합니다.

## 2. 10개 실행 파일
| 실행 파일 | 프로필 | 설정 |
|---|---|---|
| EasySave_J.exe | J_LAME_BASELINE | 320 kb/s CBR, stereo, bit reservoir 끔 |
| EasySave_K.exe | K_RESERVOIR_ON | 320 kb/s CBR, stereo, bit reservoir 켬 |
| EasySave_L.exe | L_NO_XING | 320 kb/s CBR, stereo, LAME/Xing 정보 태그 끔 |
| EasySave_M.exe | M_NO_ID3 | 320 kb/s CBR, stereo, ID3v2 태그 생략 |
| EasySave_N.exe | N_CBR_192K | 192 kb/s CBR, stereo |
| EasySave_O.exe | O_CBR_128K | 128 kb/s CBR, stereo |
| EasySave_P.exe | P_MONO_320K | 320 kb/s CBR, mono |
| EasySave_Q.exe | Q_MONO_192K | 192 kb/s CBR, mono |
| EasySave_R.exe | R_VBR_Q2 | LAME VBR 품질 2, stereo |
| EasySave_S.exe | S_48KHZ | 320 kb/s CBR, stereo, 48 kHz |

각 프로필은 공통적으로 독립 실행형 LAME 4.0을 사용합니다. 프로필별로 표시된 설정이 실제 명령행에 반영되며, 진단 로그에 실행 파일 버전과 인코딩 인자를 기록합니다.

## 3. 한글·이모지 파일명 처리
- Windows용 LAME가 한글·이모지가 포함된 최종 출력 경로를 직접 열지 않도록 ASCII 임시 경로를 사용합니다.
- 인코딩 성공 후 Python 파일 처리로 사용자가 지정한 출력 폴더와 원래 파일명에 MP3를 배치합니다.
- 진단 로그에는 임시 출력 경로, 최종 경로 이동 및 정리 결과가 기록됩니다.

## 4. 로그 기록
- 앱을 새로 실행하면 이전 `diagnostic.log` 내용을 초기화합니다.
- 실행 중에는 해당 세션의 로그를 계속 누적합니다.
- 앱을 종료한 뒤 로그 파일을 복사해 공유하면 해당 실행에서 발생한 기록만 확인할 수 있습니다.

## 5. 테스트 방법
1. ZIP 파일을 원하는 폴더에 압축 해제합니다. 폴더 안의 `_internal` 디렉터리는 이동하거나 삭제하지 마세요.
2. 동일한 원본으로 J부터 S까지 각각 MP3를 생성합니다.
3. 각 파일을 Winamp에서 재생해 소리 출력과 재생시간 표시를 확인합니다.
4. 한 번에 10개를 모두 테스트할 필요는 없습니다. 우선 J 실행 파일부터 확인하고, 결과를 알려주시면 다음 순서를 정하겠습니다.
5. 진단 로그는 앱을 종료한 뒤 복사해 공유해 주세요. 다음 실행을 시작하면 이전 로그는 초기화됩니다.

FFmpeg의 원본 디코딩 성공이나 MP3 프레임 검사만으로 Winamp 재생 호환성을 보증하지 않습니다. 최종 판정은 Winamp에서 직접 확인해야 합니다.

## 6. 구성 요소 및 라이선스
- FFmpeg: 원본 오디오 디코딩 및 PCM WAV 생성
- LAME 4.0: 독립 실행형 MP3 인코더
- LAME Windows 실행 파일은 별도 배포되는 비공식 Windows 빌드를 사용하며, 원본 프로젝트 및 배포처의 라이선스 고지를 따릅니다.
