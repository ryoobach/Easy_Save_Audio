# Easy Save Audio & Video 기능 설명서 v2.3.5

## 1. 이번 테스트 목적
Winamp에서 특정 MP3의 재생시간이 표시되지 않고 재생되지 않는 문제를 네 가지 독립 빌드로 비교합니다. 네 빌드는 각각 한 가지 출력 요소만 변경합니다.

## 2. 네 가지 테스트 빌드
| 빌드 | 변경점 | 확인하려는 가능성 |
|---|---|---|
| A_NO_XING | Xing/Info 프레임 끄기 | CBR Info 헤더 처리 호환성 |
| B_NO_ID3 | ID3v2 태그 끄기 | ID3 태그/오디오 시작 오프셋 처리 |
| C_RESERVOIR_ON | Layer III bit reservoir 켜기 | 무저장소 프레임 처리 호환성 |
| D_JOINT_STEREO | Joint Stereo 강제 | 채널 모드 처리 호환성 |

## 3. 공통 설정
- MPEG-1 Layer III, CBR 320 kb/s, 44.1 kHz, 스테레오
- FFmpeg libmp3lame 인코더
- PCM WAV 중간 변환 및 음량 정규화는 공통 유지
- 네 빌드 모두 동일한 v2.3.5 소스와 Windows 빌드 환경 사용

## 4. 테스트 방법
1. 각 아티팩트를 별도 폴더에 압축 해제합니다.
2. 같은 유튜브 원본으로 MP3를 각각 생성합니다.
3. 생성된 네 파일을 동일한 Winamp 환경에서 테스트합니다.
4. 재생시간 표시 여부와 실제 소리 재생 여부를 각각 기록합니다.

FFmpeg 진단 통과는 Winamp 호환성을 보증하지 않습니다. 최종 판정은 Winamp에서 직접 재생해 확인합니다.

## 5. 로그
각 파일의 ffmpeg_encode_started 기록에 선택된 MP3 테스트 프로파일이 남습니다. 각 빌드의 실행 파일 이름에도 프로파일명이 포함됩니다.
