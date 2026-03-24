


                            # Nemotron 3 Super 120B-A12B NVFP4 로컬 실행 세팅 가이드

> 작성일: 2026-03-12
> 모델: `NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4`
> 목적: DGX Spark(GB10 Blackwell) 환경에서 NVFP4 양자화 모델 최적 실행

---

## 1. 시스템 사양

| 항목 | 스펙 |
|------|------|
| 플랫폼 | NVIDIA DGX Spark (Project DIGITS) |
| CPU | Grace ARM (Cortex-X925 + Cortex-A725), 20코어 |
| GPU | NVIDIA GB10 (Blackwell 아키텍처) |
| 통합 메모리 | 128GB (CPU/GPU NVLink 공유) |
| 가용 메모리 | ~99GB |
| CUDA | 13.0 (V13.0.88) |
| 드라이버 | 580.126.09 |
| 아키텍처 | aarch64 (ARM) |
| 디스크 | 3.7TB NVMe, 2.4TB 가용 |
| Docker | 29.1.3 + nvidia-container-toolkit 1.18.2 |

> **핵심**: GB10은 Blackwell GPU이므로 **NVFP4 네이티브 지원**. FP8 대비 4배 빠른 추론, 1.8배 메모리 절감.
> DGX Spark는 Nemotron 3 Super의 **공식 지원 단일 GPU 플랫폼** 중 하나.

---

## 2. 모델 스펙

| 항목 | 값 |
|------|----|
| 모델명 | NVIDIA-Nemotron-3-Super-120B-A12B |
| 아키텍처 | 하이브리드 Latent MoE (Mamba-2 + MoE + Attention 인터리브) |
| 총 파라미터 | 120B |
| 활성 파라미터 | **12B** (MoE, 추론 시 전체의 10%만 활성) |
| 컨텍스트 윈도우 | **1,000,000 토큰** |
| 학습 데이터 | ~25조 토큰 |
| 지원 언어 | English, French, German, Italian, Japanese, Spanish, Chinese |
| 라이선스 | NVIDIA Open Model License |
| 출시일 | 2026-03-11 |

### 양자화별 크기 및 메모리 요구량

| 포맷 | 모델 크기 | VRAM 요구량 (추론) | DGX Spark 적합성 |
|------|----------|-------------------|-----------------|
| BF16 | ~240GB | ~250GB+ | X (메모리 초과) |
| FP8 | ~120GB | ~130GB+ | X (메모리 초과) |
| **NVFP4** | **~60-70GB** | **~70-80GB** | **O (최적)** |
| GGUF Q4 (Unsloth) | ~64-72GB | ~75-85GB | 조건부 (llama.cpp) |

> **결론**: DGX Spark 128GB 통합 메모리에서 **NVFP4가 유일하게 안정적으로 실행 가능한 공식 양자화**.
> BF16/FP8는 단일 GB10으로는 메모리 부족.

### 아키텍처 특징

- **Latent MoE**: 토큰을 소차원으로 압축 후 expert 라우팅 → 같은 비용으로 4배 expert 호출
- **Multi-Token Prediction (MTP)**: 한 번의 forward pass로 여러 미래 토큰 예측
- **NoPE**: No Positional Embeddings로 학습 → YaRN 불필요
- **Reasoning 제어**: `<think>`/`</think>` 토큰으로 추론 깊이 조절 가능

---

## 3. 실행 방식 비교

| 방식 | 장점 | 단점 | 권장도 |
|------|------|------|--------|
| **NVIDIA NIM (Docker)** | 공식 최적화, NVFP4 네이티브, 원클릭 배포 | NGC 계정 필요, 이미지 크기 큼 | **최우선 권장** |
| **vLLM** | 유연한 설정, 오픈소스 | NVFP4 지원 제한적, 별도 셋업 필요 | 권장 |
| **SGLang** | 최고 throughput/latency | 설정 복잡 | 고급 사용자 |
| **llama.cpp (GGUF)** | 경량, CPU 오프로드 가능 | MoE 성능 제한, ARM 빌드 필요 | 대안 |
| **Ollama** | 가장 간단 | GGUF 의존, 성능 차선 | 테스트용 |

---

## 4. 방법 A: NVIDIA NIM (최우선 권장)

NIM(NVIDIA Inference Microservice)은 NVFP4 모델에 대한 공식 최적화 컨테이너.

### 4-1. NGC API 키 발급

1. https://org.ngc.nvidia.com/ 접속
2. 무료 계정 생성 또는 로그인
3. 우측 상단 > Setup > Generate API Key
4. 키를 환경변수로 설정:

```bash
# ~/.bashrc 또는 ~/.zshrc에 추가
export NGC_API_KEY="nvapi-XXXXXXXXXXXXXXXXXXXXXXXXXXXX"
```

### 4-2. NIM 컨테이너 실행

```bash
# 모델 캐시 디렉토리 생성
export LOCAL_NIM_CACHE=~/.cache/nim
mkdir -p "$LOCAL_NIM_CACHE"

# NGC 레지스트리 로그인
echo "$NGC_API_KEY" | docker login nvcr.io --username '$oauthtoken' --password-stdin

# NIM 컨테이너 실행
docker run -d \
  --name nemotron3-super \
  --gpus all \
  --shm-size=16GB \
  --restart unless-stopped \
  -e NGC_API_KEY="$NGC_API_KEY" \
  -e NIM_FP4_QUANTIZE=1 \
  -v "$LOCAL_NIM_CACHE:/opt/nim/.cache" \
  -p 8000:8000 \
  nvcr.io/nim/nvidia/nemotron-3-super-120b-a12b:latest
```

> **주의**: 첫 실행 시 모델 다운로드에 10~15분 소요. 이후 캐시됨.
> **ARM 호환**: NIM 컨테이너는 multi-arch 이미지로 aarch64 자동 감지.

### 4-3. 동작 확인

```bash
# 헬스체크 (모델 로딩 완료까지 대기)
watch -n 5 'curl -s http://localhost:8000/v1/models | python3 -m json.tool'

# 테스트 요청
curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nvidia/nemotron-3-super-120b-a12b",
    "messages": [
      {"role": "user", "content": "서울 강남구 아파트 투자 시 고려할 핵심 요소 3가지를 알려주세요."}
    ],
    "max_tokens": 1024,
    "temperature": 0.6
  }' | python3 -m json.tool
```

### 4-4. Reasoning 제어 (thinking 토큰)

```bash
# thinking 활성화 (깊은 추론)
curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nvidia/nemotron-3-super-120b-a12b",
    "messages": [
      {"role": "user", "content": "다주택자 양도세 중과 배제 조건을 분석해주세요."}
    ],
    "max_tokens": 4096,
    "temperature": 0.6,
    "extra_body": {
      "chat_template_kwargs": {"reasoning_budget": 4096}
    }
  }'

# thinking 비활성화 (빠른 응답)
# reasoning_budget를 0 또는 생략
```

### 4-5. NIM 관리 명령

```bash
# 로그 확인
docker logs -f nemotron3-super

# 중지 / 시작 / 재시작
docker stop nemotron3-super
docker start nemotron3-super
docker restart nemotron3-super

# 완전 제거
docker rm -f nemotron3-super

# 캐시 정리 (모델 재다운로드 필요)
rm -rf ~/.cache/nim/nemotron*
```

---

## 5. 방법 B: vLLM (HuggingFace 모델 직접 실행)

NIM이 ARM에서 문제가 있을 경우의 대안.

### 5-1. 모델 다운로드

```bash
# HuggingFace CLI 설치 (이미 설치되어 있다면 생략)
pip install -U huggingface_hub

# NVFP4 모델 다운로드 (~60-70GB)
huggingface-cli download nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4 \
  --local-dir ~/ws/models/Nemotron-3-Super-120B-A12B-NVFP4

# 또는 FP8 (메모리 한계 주의, ~120GB)
# huggingface-cli download nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-FP8 \
#   --local-dir ~/ws/models/Nemotron-3-Super-120B-A12B-FP8
```

### 5-2. vLLM Docker 실행

```bash
# vLLM 공식 이미지 (CUDA 13.0 / ARM 호환 확인 필요)
docker run -d \
  --name nemotron3-vllm \
  --gpus all \
  --shm-size=16GB \
  --restart unless-stopped \
  -v ~/ws/models/Nemotron-3-Super-120B-A12B-NVFP4:/model \
  -p 8000:8000 \
  vllm/vllm-openai:latest \
  --model /model \
  --tensor-parallel-size 1 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.90 \
  --enforce-eager \
  --trust-remote-code \
  --quantization fp4
```

> **참고**: vLLM의 NVFP4 지원은 vLLM 버전에 따라 다름. 최신 버전 확인 필요.
> `--max-model-len`을 32768~131072 범위에서 메모리에 맞게 조절.

### 5-3. vLLM 직접 설치 (컨테이너 없이)

```bash
# vLLM 설치 (pip, ARM 빌드 필요할 수 있음)
pip install vllm

# 실행
python3 -m vllm.entrypoints.openai.api_server \
  --model ~/ws/models/Nemotron-3-Super-120B-A12B-NVFP4 \
  --tensor-parallel-size 1 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.90 \
  --port 8000
```

---

## 6. 방법 C: llama.cpp + GGUF (경량 대안)

### 6-1. GGUF 모델 다운로드

```bash
# Unsloth Dynamic 2.0 양자화 - Q4 추천 (DGX Spark 메모리 적합)
huggingface-cli download unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF \
  --include "UD-Q4_K_XL/*" \
  --local-dir ~/ws/models/Nemotron-3-Super-GGUF-Q4
```

> **주의**: Unsloth GGUF Q4_K_XL에서 최신 llama.cpp master 브랜치에서 로드 실패 이슈가 보고됨.
> 안정 버전 확인 후 다운로드 권장.

### 6-2. llama.cpp 빌드 (ARM + CUDA)

```bash
git clone https://github.com/ggml-org/llama.cpp.git
cd llama.cpp
cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES="100" # GB10 = SM 100
cmake --build build --config Release -j$(nproc)
```

### 6-3. 실행

```bash
./build/bin/llama-server \
  -m ~/ws/models/Nemotron-3-Super-GGUF-Q4/model.gguf \
  -ngl 999 \
  -c 32768 \
  --host 0.0.0.0 \
  --port 8000
```

---

## 7. 방법 D: Ollama (가장 간단, 테스트용)

```bash
# Ollama 설치 (이미 설치되어 있다면 생략)
curl -fsSL https://ollama.com/install.sh | sh

# 모델 pull & 실행
ollama pull nemotron3-super:120b-q4
ollama run nemotron3-super:120b-q4
```

> **주의**: Ollama의 Nemotron 3 Super 지원은 커뮤니티 GGUF 기반. 공식 NVFP4 대비 성능 열세.
> API 서버로 사용 시: `ollama serve` (기본 포트 11434)

---

## 8. OpenAI 호환 API 연동 (공통)

NIM, vLLM, llama.cpp 모두 OpenAI 호환 API 제공. 기존 코드에서 endpoint만 변경.

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"  # 로컬 실행 시 아무 값
)

response = client.chat.completions.create(
    model="nvidia/nemotron-3-super-120b-a12b",  # NIM 모델명
    # model="/model",  # vLLM 모델명
    messages=[
        {"role": "system", "content": "당신은 대한민국 부동산 전문 어드바이저입니다."},
        {"role": "user", "content": "2026년 서울 강남구 재건축 시장 전망을 분석해주세요."}
    ],
    max_tokens=2048,
    temperature=0.6
)

print(response.choices[0].message.content)
```

---

## 9. 성능 벤치마크 참고

| 벤치마크 | Nemotron 3 Super | Qwen3.5-122B | DeepSeek-R1 |
|---------|-----------------|-------------|------------|
| PinchBench (에이전트) | **85.6%** | - | - |
| LiveCodeBench | **81.19** | 78.93 | - |
| HMMT (수학) | **93.67** | 91.40 | - |
| SWE-Bench Verified | 60.47% | ~66% | - |
| 토큰 생성 속도 | **3.45 tok/step** | - | 2.70 |

**처리량 비교 (동일 하드웨어):**
- Qwen3.5-122B 대비 **7.5배** throughput (12B만 활성)
- GPT-OSS-120B 대비 **2.2배** throughput

---

## 10. RAG 프로젝트 연동 메모

- **컨텍스트 윈도우 1M 토큰**: 대규모 문서 일괄 처리에 유리 (v2 변환 배치 크기 증가 가능)
- **Tool calling 지원**: Phase 2 이후 실거래 DB API 연동 시 에이전트 활용 가능
- **추론 제어**: `reasoning_budget`으로 간단한 분류(REJECT 판정)는 빠르게, 복잡한 분석은 깊게 설정
- **한국어**: 공식 지원 언어에 포함되지 않으나, 학습 데이터에 한국어 포함 (성능 별도 검증 필요)

> **중요**: 한국어가 공식 지원 언어(EN/FR/DE/IT/JA/ES/ZH)에 없으므로,
> 실제 v2 변환 작업에 투입 전 Claude/Codex 대비 한국어 품질 비교 테스트 필수.

---

## 11. 트러블슈팅

### NIM 컨테이너가 시작되지 않을 때
```bash
# 로그 확인
docker logs nemotron3-super 2>&1 | tail -50

# GPU 인식 확인
docker run --rm --gpus all nvidia/cuda:13.0.0-base-ubuntu24.04 nvidia-smi

# 메모리 부족 시 max-model-len 축소 또는 다른 프로세스 종료
```

### ARM 호환성 문제
```bash
# 아키텍처 확인
uname -m  # aarch64

# Docker 이미지 아키텍처 확인
docker manifest inspect nvcr.io/nim/nvidia/nemotron-3-super-120b-a12b:latest | grep architecture
```

### 메모리 부족 (OOM)
- `--max-model-len` 값을 줄여서 KV cache 메모리 감소 (32768 → 16384 → 8192)
- X11/Gnome 데스크톱 종료로 ~600MB GPU 메모리 확보
- 다른 서비스(Qdrant, 임베딩 서버 등) 임시 중지

### 모델 다운로드 실패
```bash
# HuggingFace 토큰 설정
huggingface-cli login

# NGC 토큰 갱신
docker logout nvcr.io
echo "$NGC_API_KEY" | docker login nvcr.io --username '$oauthtoken' --password-stdin
```

---

## 참고 링크

- [NVIDIA Research - Nemotron 3 Super](https://research.nvidia.com/labs/nemotron/Nemotron-3-Super/)
- [NVIDIA Developer Blog](https://developer.nvidia.com/blog/introducing-nemotron-3-super-an-open-hybrid-mamba-transformer-moe-for-agentic-reasoning/)
- [HuggingFace - NVFP4](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4)
- [HuggingFace - BF16](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16)
- [HuggingFace - FP8](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-FP8)
- [Unsloth GGUF](https://huggingface.co/unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF)
- [NVIDIA NIM Catalog](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/modelcard)
- [SGLang Cookbook](https://cookbook.sglang.io/autoregressive/NVIDIA/Nemotron3-Super)
- [NVIDIA NeMo Nemotron GitHub](https://github.com/NVIDIA-NeMo/Nemotron)
- [NVFP4 기술 블로그](https://developer.nvidia.com/blog/introducing-nvfp4-for-efficient-and-accurate-low-precision-inference/)
