# AI 설정 문서

로컬 LLM 실행 및 AI 환경 설정 관련 문서 모음.

## 문서 목록

| 파일 | 내용 |
|------|------|
| [qwen35_27b_setup.md](./qwen35_27b_setup.md) | Qwen3.5-27B 로컬 실행 및 테스트 가이드 |

## 현재 서버 환경 요약

- **CPU**: NVIDIA Grace (aarch64 ARM)
- **RAM**: 120GB 통합 메모리 (NVLink)
- **GPU**: NVIDIA GB200 / Grace Blackwell Superchip
- **CUDA**: 13.0.2 / Driver: 580.95.05
- **로컬 모델**: `~/ws/models/Qwen3.5-27B` (52GB, BF16)
