# 환경 설정 문서

로컬 LLM 실행, 임베딩 모델, 벡터 DB 등 AI 인프라 환경 설정 관련 문서 모음.

## 문서 목록

| 파일 | 내용 |
|------|------|
| [qwen35_27b_setup.md](./qwen35_27b_setup.md) | Qwen3.5-27B 로컬 실행 및 테스트 가이드 |
| [embedding_container_setup.md](./embedding_container_setup.md) | KURE-v1 임베딩 모델 컨테이너 실행 가이드 |
| [qdrant_container_setup.md](./qdrant_container_setup.md) | Qdrant 벡터 DB 컨테이너 실행 가이드 |

## 현재 서버 환경 요약

- **CPU**: NVIDIA Grace (aarch64 ARM)
- **RAM**: 120GB 통합 메모리 (NVLink)
- **GPU**: NVIDIA GB10 (sm_121, Blackwell)
- **CUDA**: 13.0.2 / Driver: 580.126.09
- **Docker**: 29.1.3 (nvidia runtime 내장)
- **NGC 이미지**: `nvcr.io/nvidia/pytorch:25.11-py3` (로컬 캐시 완료)
- **로컬 모델**: `~/ws/models/Qwen3.5-27B` (52GB, BF16), `nlpai-lab/KURE-v1` (2.3GB)
