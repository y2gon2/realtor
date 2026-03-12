# KURE-v1 임베딩 모델 컨테이너 실행 가이드 (DGX Spark)

> 작성일: 2026-03-08
> 모델: `nlpai-lab/KURE-v1` (568M params, 1024차원, 8192 토큰)
> 목적: DGX Spark(GB10)에서 임베딩 모델을 컨테이너로 안정적으로 실행

---

## 1. DGX Spark 하드웨어 제약사항

### 왜 일반 pip install이 안 되는가?

DGX Spark는 3가지 면에서 일반적인 GPU 서버와 다릅니다:

| 항목 | 일반 GPU 서버 | DGX Spark (GB10) |
|------|-------------|-------------------|
| CPU 아키텍처 | x86_64 | **aarch64 (ARM)** |
| CUDA 버전 | 12.x | **13.0** |
| GPU Compute Capability | sm_80~90 | **sm_121 (Blackwell)** |
| GPU 메모리 | 별도 VRAM | **128GB 통합 메모리 (CPU/GPU 공유)** |

이로 인해:
- PyPI의 `pip install torch`는 **x86 + CUDA 12.x** wheel → 아키텍처 불일치로 실패
- CUDA 12.x 빌드의 `libcudart.so.12` → DGX Spark의 `libcudart.so.13`과 호환 불가
- sm_121을 지원하지 않는 PyTorch 빌드 → GPU 인식 실패

### 현재 시스템 사양

```
CPU:      NVIDIA Grace (aarch64 ARM)
GPU:      NVIDIA GB10 (sm_121, Blackwell)
RAM:      128GB LPDDR5x 통합 메모리 (CPU/GPU 공유, NVLink)
CUDA:     13.0.2 (nvcc V13.0.88)
Driver:   580.126.09
OS:       Ubuntu 24.04 (Linux 6.17.0-1008-nvidia, aarch64)
Docker:   29.1.3 (nvidia runtime 포함)
```

---

## 2. 컨테이너 전략 비교

### 사용 가능한 베이스 이미지

| 이미지 | CUDA | PyTorch | 용도 | 크기 |
|--------|------|---------|------|------|
| `nvcr.io/nvidia/pytorch:25.11-py3` ✅ | 13.0.2 | 2.10.0a0 | 범용 ML/DL | ~19.5GB |
| `nvcr.io/nvidia/pytorch:25.12-py3` | 13.1.0 | 2.10.0a0 | 최신 안정 | ~20GB |
| `nvcr.io/nvidia/pytorch:26.01-py3` | 13.1.1 | 2.10+ | 최신 | ~20GB |
| `nvcr.io/nvidia/cuda:13.0.1-devel-ubuntu24.04` | 13.0.1 | 없음 | 경량 빌드 | ~5GB |

> **`nvcr.io/nvidia/pytorch:25.11-py3`는 이미 로컬에 존재합니다 (19.5GB).**

### 사용하면 안 되는 이미지

| 이미지 | 문제 |
|--------|------|
| `nvcr.io/nvidia/l4t-pytorch:*` | Jetson(L4T) 전용, DGX Spark와 드라이버 스택 다름 |
| `pytorch/pytorch:*` (Docker Hub) | x86_64 전용 |
| PyPI `pip install torch` | x86 + CUDA 12.x wheel, aarch64 미지원 |

### KURE-v1 모델 특성

```
파라미터:   568M
모델 크기:  ~2.3GB (safetensors)
임베딩 차원: 1,024
최대 토큰:  8,192
VRAM 요구:  ~3~4GB (FP16 추론 기준)
→ 128GB 통합 메모리에서 여유롭게 실행 가능
```

---

## 3. 유사 사례 조사

### 사례 1: NVIDIA 공식 — sentence-transformers on DGX Spark

**출처**: [NVIDIA Forums — Unable to run sentence-transformers examples](https://forums.developer.nvidia.com/t/unable-to-simple-run-sentence-transformers-examples/348867)

- **문제**: DGX Spark에서 `pip install sentence-transformers` 후 실행 시 CUDA 호환성 오류
- **원인**: PyPI torch wheel이 CUDA 12.x / x86 바이너리 → `libcudart.so.13` 누락 에러
- **해결**: NGC PyTorch 컨테이너 내부에서 sentence-transformers 설치

### 사례 2: NVIDIA Embedding NIM 실패

**출처**: [NVIDIA Forums — Embedding NIM fails on DGX Spark](https://forums.developer.nvidia.com/t/dgx-spark-gb10-arm64-embedding-nim-llama-3-2-nv-embedqa-1b-v2-1-10-0-fails-with-cudaerrorsymbolnotfound-onnx-runtime/354998)

- **문제**: NVIDIA의 공식 Embedding NIM도 `cudaErrorSymbolNotFound` 에러
- **원인**: NIM 내부 ONNX Runtime이 sm_121 커널 미포함
- **교훈**: 상용 솔루션도 DGX Spark 미지원 → PyTorch 기반 직접 실행이 가장 안정적

### 사례 3: gtoscano/SparkTransformer

**출처**: [GitHub — gtoscano/SparkTransformer](https://github.com/gtoscano/SparkTransformer)

- NGC PyTorch 컨테이너 기반 HuggingFace Transformers 경량 환경
- Dockerfile 패턴: `FROM nvcr.io/nvidia/pytorch:25.11-py3` → pip install 추가 패키지
- DGX Spark에서 검증 완료

### 사례 4: NVIDIA 공식 Playbooks

**출처**: [GitHub — NVIDIA/dgx-spark-playbooks](https://github.com/NVIDIA/dgx-spark-playbooks)

- 29개 공식 가이드 (RAG, 임베딩, LLM 서빙 등)
- NGC 컨테이너 기반 워크플로우 표준화
- 핵심 패턴: `--gpus all --ipc=host` + HuggingFace 캐시 마운트

### 사례 5: sm_120 / sm_121 바이너리 호환성

**출처**: [NVIDIA Forums — DGX Spark GB10 CUDA Compute Capability](https://forums.developer.nvidia.com/t/dgx-spark-gb10-cuda-compute-capability/342864)
**출처**: [PyTorch GitHub — SM_120 Support Issue #164342](https://github.com/pytorch/pytorch/issues/164342)

- sm_120과 sm_121은 **바이너리 호환** → sm_120 빌드가 sm_121에서 실행됨
- NGC 25.11+ 컨테이너는 sm_120 커널 포함 → GB10에서 정상 동작
- 데이터센터 Blackwell(sm_100)과는 **호환 불가** (TMEM 차이)

---

## 4. 추천 방식: NGC 컨테이너 + sentence-transformers

### 4-1. 방식 A — 직접 컨테이너 실행 (빠른 테스트)

기존 이미지(`pytorch:25.11-py3`)를 바로 사용:

```bash
docker run --gpus all -it --rm \
  --ipc=host \
  -v $HOME/.cache/huggingface:/root/.cache/huggingface \
  -v $HOME/ws/models:/models \
  -v $HOME/ws/rag:/workspace \
  -w /workspace \
  nvcr.io/nvidia/pytorch:25.11-py3 \
  bash
```

컨테이너 내부에서:

```bash
# sentence-transformers 설치 (컨테이너의 CUDA 13 PyTorch 사용)
pip install "numpy<2.0" sentence-transformers

# KURE-v1 테스트 (로컬 모델 경로 사용)
python3 -c "
from sentence_transformers import SentenceTransformer
import torch

print(f'CUDA available: {torch.cuda.is_available()}')
print(f'Device: {torch.cuda.get_device_name(0)}')

model = SentenceTransformer('/models/KURE-v1')
embeddings = model.encode(['강남 아파트 투자 전략은?', '서초구 재건축 시세 동향'])
print(f'Embedding shape: {embeddings.shape}')
print(f'Cosine similarity: {embeddings[0] @ embeddings[1] / (sum(embeddings[0]**2)**0.5 * sum(embeddings[1]**2)**0.5):.4f}')
print('OK — KURE-v1 정상 동작')
"
```

### 4-2. 방식 B — 전용 Dockerfile 빌드 (프로덕션 권장)

```dockerfile
# Dockerfile.embedding
FROM nvcr.io/nvidia/pytorch:25.11-py3

# NumPy 2.x 호환성 이슈 방지
RUN pip install --no-cache-dir "numpy<2.0"

# sentence-transformers + 의존성
RUN pip install --no-cache-dir \
    sentence-transformers \
    qdrant-client

# KURE-v1 모델 사전 다운로드 (빌드 시 캐싱)
RUN python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('/models/KURE-v1')"

WORKDIR /workspace

# 기본 진입점
CMD ["python3"]
```

빌드 및 실행:

```bash
# 빌드
cd ~/ws/rag
docker build -f Dockerfile.embedding -t rag-embedding:latest .

# 실행
docker run --gpus all -it --rm \
  --ipc=host \
  -v $HOME/.cache/huggingface:/root/.cache/huggingface \
  -v $HOME/ws/models:/models \
  -v $HOME/ws/rag:/workspace \
  -w /workspace \
  rag-embedding:latest
```

### 4-3. 방식 C — Docker Compose (서비스화, 장기 운영)

```yaml
# docker-compose.embedding.yml
services:
  embedding:
    image: rag-embedding:latest
    build:
      context: .
      dockerfile: Dockerfile.embedding
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    ipc: host
    volumes:
      - ~/.cache/huggingface:/root/.cache/huggingface
      - ~/ws/models:/models
      - ./:/workspace
    working_dir: /workspace
    # 임베딩 서버로 사용 시 (FastAPI 등)
    # command: python3 embedding_server.py
    # ports:
    #   - "8001:8001"
    restart: unless-stopped
```

---

## 5. 핵심 주의사항

### NumPy 버전 충돌

NGC 컨테이너의 PyTorch 확장은 NumPy 1.x로 빌드됨. NumPy 2.x 설치 시 `ABI incompatible` 에러 발생:

```bash
# 반드시 NumPy 1.x 유지
pip install "numpy<2.0"
```

### HuggingFace 캐시 마운트

모델을 매번 다운로드하지 않으려면 호스트의 캐시 디렉토리를 마운트:

```bash
-v $HOME/.cache/huggingface:/root/.cache/huggingface
```

이미 다운로드한 KURE-v1 모델이 자동으로 인식됩니다.

### 로컬 모델 경로 사용 (오프라인)

모델을 특정 디렉토리에 저장해둔 경우:

```python
model = SentenceTransformer('/models/KURE-v1')
```

### ipc=host 플래그

PyTorch DataLoader의 공유 메모리(shared memory) 사용을 위해 필수:

```bash
--ipc=host  # 또는 --shm-size=16g
```

### Flash Attention

DGX Spark(aarch64)에서 flash-attention은 **사전 빌드 wheel이 없어** 소스 빌드 필요.
KURE-v1(568M)은 모델이 작아 flash-attention 없이도 충분히 빠름 — 당장은 불필요.

---

## 6. 검증 스크립트

컨테이너 내부에서 전체 파이프라인 검증:

```python
# test_embedding.py
import time
import torch
from sentence_transformers import SentenceTransformer

# 1. 환경 확인
print("=" * 60)
print(f"PyTorch:    {torch.__version__}")
print(f"CUDA:       {torch.version.cuda}")
print(f"GPU:        {torch.cuda.get_device_name(0)}")
print(f"Compute:    {torch.cuda.get_device_capability(0)}")
print("=" * 60)

# 2. 모델 로드
start = time.time()
model = SentenceTransformer("/models/KURE-v1")
print(f"\n모델 로드: {time.time() - start:.1f}s")

# 3. 임베딩 테스트 — 부동산 도메인 쿼리
queries = [
    "강남구 아파트 매매 실거래가 추이",
    "재건축 초과이익환수제란 무엇인가",
    "DSR 40% 규제가 대출한도에 미치는 영향",
    "경매 낙찰가율이 높은 지역은 어디인가",
    "전세사기 예방을 위한 체크리스트",
]

start = time.time()
embeddings = model.encode(queries, show_progress_bar=True)
elapsed = time.time() - start

print(f"\n임베딩 완료: {len(queries)}건, {elapsed:.2f}s ({len(queries)/elapsed:.1f} docs/sec)")
print(f"임베딩 차원: {embeddings.shape}")

# 4. 유사도 매트릭스
from sentence_transformers.util import cos_sim
sim_matrix = cos_sim(embeddings, embeddings)
print("\n유사도 매트릭스:")
for i, q in enumerate(queries):
    print(f"  [{i}] {q[:30]}...")
print()
for i in range(len(queries)):
    row = " ".join(f"{sim_matrix[i][j]:.3f}" for j in range(len(queries)))
    print(f"  [{i}] {row}")

# 5. 배치 처리 성능 (실제 워크로드 시뮬레이션)
batch_sizes = [1, 8, 32, 64]
test_text = "서울 강남구 아파트 매매 시장 동향 분석"

print(f"\n{'배치 크기':>10} {'처리시간':>10} {'처리량':>15}")
print("-" * 40)
for bs in batch_sizes:
    texts = [test_text] * bs
    start = time.time()
    _ = model.encode(texts)
    elapsed = time.time() - start
    print(f"{bs:>10} {elapsed:>9.3f}s {bs/elapsed:>13.1f} docs/sec")

print("\n✅ 모든 테스트 통과")
```

---

## 7. 빠른 시작 요약

```bash
# 1. 이미 가지고 있는 NGC 이미지로 컨테이너 진입
docker run --gpus all -it --rm \
  --ipc=host \
  -v $HOME/.cache/huggingface:/root/.cache/huggingface \
  -v $HOME/ws/models:/models \
  -v $HOME/ws/rag:/workspace \
  -w /workspace \
  nvcr.io/nvidia/pytorch:25.11-py3 bash

# 2. 패키지 설치 (컨테이너 내부)
pip install "numpy<2.0" sentence-transformers

# 3. KURE-v1 동작 확인
python3 -c "
from sentence_transformers import SentenceTransformer
model = SentenceTransformer('/models/KURE-v1')
emb = model.encode(['테스트'])
print(f'Shape: {emb.shape}, OK')
"

# 4. 검증 스크립트 실행
python3 test_embedding.py
```

---

## 8. 향후 확장

### Qdrant 연동 (Phase 1 RAG MVP)

```python
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

client = QdrantClient(host="localhost", port=6333)

# KURE-v1 1024차원에 맞춘 컬렉션 생성
client.create_collection(
    collection_name="real_estate_notes",
    vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
)
```

### BM25 하이브리드 검색

KURE-v1은 Dense 전용이므로 Sparse 검색은 별도 구성 필요:

```
하이브리드 검색 아키텍처:
  ├─ Dense: KURE-v1 (sentence-transformers) → Qdrant 벡터 검색
  └─ Sparse: Qdrant BM25 / fastembed sparse 또는 별도 BM25 인덱스
```

---

## 참고 자료

- [nlpai-lab/KURE-v1 — Hugging Face](https://huggingface.co/nlpai-lab/KURE-v1)
- [NVIDIA DGX Spark 공식 문서 — Container Runtime](https://docs.nvidia.com/dgx/dgx-spark/nvidia-container-runtime-for-docker.html)
- [NVIDIA DGX Spark 포팅 가이드](https://docs.nvidia.com/dgx/dgx-spark-porting-guide/)
- [NVIDIA/dgx-spark-playbooks — GitHub](https://github.com/NVIDIA/dgx-spark-playbooks)
- [gtoscano/SparkTransformer — GitHub](https://github.com/gtoscano/SparkTransformer)
- [natolambert/dgx-spark-setup — GitHub](https://github.com/natolambert/dgx-spark-setup)
- [NGC PyTorch 컨테이너 릴리스 노트](https://docs.nvidia.com/deeplearning/frameworks/pytorch-release-notes/index.html)
- [DGX Spark GB10 Compute Capability — NVIDIA Forums](https://forums.developer.nvidia.com/t/dgx-spark-gb10-cuda-compute-capability/342864)
- [sentence-transformers on DGX Spark — NVIDIA Forums](https://forums.developer.nvidia.com/t/unable-to-simple-run-sentence-transformers-examples/348867)
- [Blackwell 호환성 가이드 — NVIDIA](https://docs.nvidia.com/cuda/blackwell-compatibility-guide/)
