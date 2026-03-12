# Qwen3.5-27B 로컬 실행 세팅 가이드

> 작성일: 2026-03-03
> 모델 경로: `~/ws/models/Qwen3.5-27B`
> 목적: 현재 서버에 최적화된 모델 실행 및 테스트

---

## 1. 시스템 사양

| 항목 | 스펙 |
|------|------|
| CPU 아키텍처 | aarch64 (NVIDIA Grace ARM CPU) |
| 시스템 RAM | 120GB (통합 메모리, NVLink 공유) |
| 가용 RAM | ~99GB |
| GPU | NVIDIA GB200 / Grace Blackwell Superchip (PCI 0x2e12) |
| CUDA 버전 | 13.0.2 |
| NVIDIA 드라이버 | 580.95.05 |
| NVLink | Fabric Manager + IMEX (NVLink 메모리 맵핑) 탑재 |
| OS / 커널 | Linux 6.17.0-1008-nvidia (Ubuntu, aarch64) |
| Python | 3.12.3 |

> **참고**: `nvidia-smi`가 현재 응답 없음 → 드라이버가 로드되어 있지 않거나, Grace Blackwell 전용 경로 필요.
> CUDA 바이너리와 Fabric Manager는 정상 설치되어 있으므로 torch/vLLM 설치 후 GPU 인식 가능.

---

## 2. 모델 스펙

| 항목 | 값 |
|------|----|
| 모델명 | Qwen3.5-27B |
| 아키텍처 | `Qwen3_5ForConditionalGeneration` (멀티모달 지원) |
| 파라미터 | 약 27B |
| 정밀도 | BF16 |
| 파일 크기 | 52GB (safetensors 11분할) |
| 레이어 수 | 64 |
| Hidden Size | 5120 |
| 어텐션 구조 | 하이브리드 (linear_attention × 3 + full_attention × 1 반복) |
| Vocab Size | 248,320 |
| Head Dim | 256 |

**VRAM/RAM 요구량 추정:**
- BF16 전체 로드: ~54GB
- KV Cache (context 8K 기준): ~4–8GB 추가
- **합계: ~60–65GB** → 120GB 통합 메모리로 충분

---

## 3. 추천 실행 방식

### 권장 순서

```
1순위: vLLM (GPU 서빙, 최고 성능)
2순위: HuggingFace Transformers + Accelerate (빠른 테스트)
3순위: llama.cpp (CPU 추론, 설치 불필요시)
```

Grace Blackwell 시스템에서는 **vLLM**이 최적.
NVLink 통합 메모리를 최대 활용하고, OpenAI 호환 API 서버로 바로 사용 가능.

---

## 4. 환경 세팅

### 4-1. 전용 가상환경 생성

```bash
cd ~/ws
python3 -m venv venv_llm
source ~/ws/venv_llm/bin/activate
```

### 4-2. vLLM 설치 (aarch64 + CUDA 13.0 대응)

```bash
# pip 최신화
pip install --upgrade pip

# PyTorch (CUDA 13.0 / aarch64 Grace Blackwell용)
# NVIDIA NGC 또는 공식 빌드 사용
pip install torch torchvision torchaudio \
  --index-url https://pypi.nvidia.com/  # NGC wheel 우선

# 또는 소스 빌드가 필요할 경우 (CUDA 13.0 미지원 wheel 없을 때)
# pip install torch --pre --index-url https://download.pytorch.org/whl/nightly/cu124

# vLLM 설치
pip install vllm

# 필수 패키지
pip install transformers accelerate huggingface_hub
```

> **주의**: CUDA 13.0은 매우 최신이므로 기존 stable wheel이 없을 수 있음.
> NGC(https://catalog.ngc.nvidia.com)에서 Grace Blackwell 전용 PyTorch 컨테이너 또는 wheel 사용 권장.

### 4-3. Docker 방식 (권장)

> **주의**: 아래 이미지들은 GB10(SM121, CUDA capability 12.1)에서 동작하지 않음:
> - `nvcr.io/nvidia/pytorch:24.07-py3` — GB10/Blackwell GPU 미지원
> - `nvcr.io/nvidia/pytorch:25.11-py3` — CUDA 13 기반이나 PyPI vLLM wheel(CUDA 12용)과 호환 불가
> - `vllm/vllm-openai:latest` — x86_64 + CUDA 12 전용
> - `scitrera/dgx-spark-vllm:0.16.1-dev-3bbb2046-t5` — PyTorch가 CUDA capability 12.0까지만 지원 (GB10은 12.1)
>
> **GB10 전용으로 빌드된 커뮤니티 이미지를 사용해야 합니다.**

```bash
# GB10(SM121) 전용 vLLM 이미지 (권장)
docker pull scitrera/dgx-spark-vllm:0.16.1-dev-3bbb2046-t5

# 대안: lharillo/vllm-blackwell-gb10-spark (vLLM v0.14.0 기반, 안정적이나 구버전)
# docker pull lharillo/vllm-blackwell-gb10-spark:latest
```

---

## 5. vLLM 서버 실행

> **사전 조건**: 이 이미지의 transformers 5.2.0.dev0에 Qwen3.5 RoPE 파싱 버그가 있어
> 컨테이너 시작 시 `pip install --upgrade transformers`가 필요함.
> docker-compose 파일에서는 자동 처리됨.

### 5-1. Docker Compose로 실행 (권장)

```bash
cd ~/ws/models
docker compose up -d

# 로그 확인 (모델 로딩 완료까지 수 분 소요)
docker compose logs -f qwen35-27b

# 중지
docker compose down
```

> docker-compose 파일: `~/ws/models/docker-compose.yml`

### 5-2. bash로 진입 후 수동 실행 (디버깅 시)

```bash
docker run --gpus all --ipc=host --network=host \
  -v ~/ws/models:/models \
  -v ~/ws/rag:/workspace \
  -it --entrypoint bash \
  scitrera/dgx-spark-vllm:0.16.1-dev-3bbb2046-t5

# 컨테이너 내부에서
pip install --upgrade transformers -q

vllm serve /models/Qwen3.5-27B \
  --max-model-len 32768 \
  --tensor-parallel-size 1 \
  --gpu-memory-utilization 0.70 \
  --max-num-seqs 8 \
  --enable-prefix-caching \
  --enable-chunked-prefill \
  --max-num-batched-tokens 4096 \
  --port 8000 \
  --host 0.0.0.0 \
  --served-model-name qwen35-27b
```

### 5-3. 최적화 옵션 설명

| 옵션 | 현재 값 | 설명 |
|------|---------|------|
| `--max-model-len 32768` | 32K | thinking 모드 사용 시 긴 출력 대응. 메모리 여유 시 65536까지 가능 |
| `--gpu-memory-utilization 0.60` | 60% | 가용 메모리 75GB 기준 ~45GB 사용. 다른 프로세스 정리 시 0.85로 상향 |
| `--max-num-seqs 8` | 8 | 동시 요청 수. thinking 모드는 출력이 길어 낮게 설정 |
| `--enable-prefix-caching` | on | RAG 반복 시스템 프롬프트 캐싱으로 TTFT 단축 |
| `--enable-chunked-prefill` | on | 긴 컨텍스트 입력 시 메모리 효율화 |
| `--max-num-batched-tokens 4096` | 4096 | prefill 배치 크기. 메모리 사용량과 처리량 균형 |

> **메모리 여유 시 (다른 프로세스 정리 후)**: `--gpu-memory-utilization 0.85`로 변경하면
> KV cache가 늘어나 더 긴 컨텍스트와 동시 요청을 처리할 수 있음.

---

## 6. HuggingFace Transformers로 빠른 테스트

설치 전 빠른 동작 확인이 필요할 때:

```bash
pip install transformers accelerate

python3 << 'EOF'
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_PATH = "/home/gon/ws/models/Qwen3.5-27B"

print("Loading tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)

print("Loading model...")
model = AutoModelForCausalLM.from_pretrained(
    MODEL_PATH,
    torch_dtype=torch.bfloat16,
    device_map="auto",          # 자동으로 GPU/CPU 분배
    low_cpu_mem_usage=True,
)

print("Model loaded!")
print(f"Device: {next(model.parameters()).device}")

# 테스트 추론
messages = [
    {"role": "user", "content": "서울 강남구 아파트 투자 시 주의할 점은?"}
]
text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
inputs = tokenizer(text, return_tensors="pt").to(model.device)

with torch.no_grad():
    outputs = model.generate(
        **inputs,
        max_new_tokens=512,
        temperature=0.7,
        do_sample=True,
        repetition_penalty=1.1,
    )

response = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
print("\n=== 응답 ===")
print(response)
EOF
```

---

## 7. API 서버 테스트

vLLM 서버 실행 후 테스트:

### 7-1. curl 테스트

```bash
# 모델 목록 확인
curl http://localhost:8000/v1/models

# 채팅 완성 테스트
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen35-27b",
    "messages": [
      {
        "role": "system",
        "content": "당신은 대한민국 부동산 전문 AI 어드바이저입니다."
      },
      {
        "role": "user",
        "content": "서울 마포구 아파트 시장 현황을 알려주세요."
      }
    ],
    "temperature": 0.7,
    "max_tokens": 1024
  }'
```

### 7-2. Python 클라이언트 테스트

```python
# test_qwen_api.py
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-needed"  # vLLM은 API 키 불필요
)

def test_real_estate_query(question: str) -> str:
    response = client.chat.completions.create(
        model="qwen35-27b",
        messages=[
            {
                "role": "system",
                "content": "당신은 대한민국 부동산 전문 AI 어드바이저입니다. "
                           "구체적이고 정확한 정보를 제공해주세요."
            },
            {"role": "user", "content": question}
        ],
        temperature=0.7,
        max_tokens=2048,
    )
    return response.choices[0].message.content

# 테스트 케이스
test_cases = [
    "서울 강남구와 마포구 아파트 투자 비교 분석해줘",
    "2025년 부동산 양도세 계산 방법 알려줘",
    "서울 재개발/재건축 투자 시 주의사항은?",
    "DSR 40% 규제가 내 대출 한도에 미치는 영향을 설명해줘",
]

for q in test_cases:
    print(f"\n질문: {q}")
    print(f"답변: {test_real_estate_query(q)}")
    print("-" * 80)
```

### 7-3. 스트리밍 테스트

```python
# test_streaming.py
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed")

stream = client.chat.completions.create(
    model="qwen35-27b",
    messages=[{"role": "user", "content": "강남 아파트 시장 전망을 상세히 설명해줘"}],
    max_tokens=1024,
    stream=True,
)

for chunk in stream:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
print()
```

---

## 8. 성능 벤치마크 테스트

```python
# benchmark_qwen.py
import time
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed")

def benchmark(prompt: str, max_tokens: int = 512, n_runs: int = 3):
    times = []
    token_counts = []

    for i in range(n_runs):
        start = time.time()
        resp = client.chat.completions.create(
            model="qwen35-27b",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        elapsed = time.time() - start

        out_tokens = resp.usage.completion_tokens
        times.append(elapsed)
        token_counts.append(out_tokens)

    avg_time = sum(times) / n_runs
    avg_tokens = sum(token_counts) / n_runs
    tps = avg_tokens / avg_time

    print(f"평균 응답시간: {avg_time:.2f}s")
    print(f"평균 출력 토큰: {avg_tokens:.0f}")
    print(f"처리량 (tokens/sec): {tps:.1f}")
    return tps

# 다양한 길이 테스트
print("=== 짧은 응답 테스트 ===")
benchmark("강남구 아파트 평균 가격은?", max_tokens=128)

print("\n=== 중간 응답 테스트 ===")
benchmark("재개발 투자 전략을 설명해줘", max_tokens=512)

print("\n=== 긴 응답 테스트 ===")
benchmark("서울 주요 지역 부동산 시장 분석 리포트를 작성해줘", max_tokens=2048)
```

---

## 9. RAG 프로젝트 연동

현재 RAG 프로젝트(부동산 AI 어드바이저)와 연동 시:

```python
# rag/llm_client.py
from openai import OpenAI
from typing import Iterator

class QwenLLMClient:
    def __init__(self, base_url: str = "http://localhost:8000/v1"):
        self.client = OpenAI(base_url=base_url, api_key="not-needed")
        self.model = "qwen35-27b"

    def chat(self, messages: list[dict], **kwargs) -> str:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 2048),
        )
        return resp.choices[0].message.content

    def stream(self, messages: list[dict], **kwargs) -> Iterator[str]:
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 2048),
            stream=True,
        )
        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

# 사용 예시
llm = QwenLLMClient()
answer = llm.chat([
    {"role": "system", "content": "당신은 부동산 전문 AI입니다."},
    {"role": "user", "content": "서울 강남구 아파트 매수 타이밍은?"}
])
```

---

## 10. 트러블슈팅

### nvidia-smi 실패 문제

```bash
# Grace Blackwell에서 nvidia-smi 경로 확인
which nvidia-smi
ls /usr/bin/nvidia-smi
ls /usr/local/bin/nvidia-smi

# 드라이버 로드 확인
lsmod | grep nvidia
modprobe nvidia 2>/dev/null

# NVSMI 환경변수 확인
echo $CUDA_VISIBLE_DEVICES
```

### GPU 미인식 시 (CPU 폴백)

```bash
# CPU만으로 추론 (느리지만 동작은 함 - 120GB RAM 활용)
CUDA_VISIBLE_DEVICES="" python -m vllm.entrypoints.openai.api_server \
  --model ~/ws/models/Qwen3.5-27B \
  --dtype float32 \
  --device cpu \
  --max-model-len 8192 \
  --port 8000
```

### 메모리 부족 시

```bash
# max-model-len 줄이기
--max-model-len 16384

# gpu-memory-utilization 낮추기
--gpu-memory-utilization 0.75

# 4-bit 양자화 (품질 저하 있음)
pip install bitsandbytes
--quantization bitsandbytes --load-format bitsandbytes
```

### vLLM이 Qwen3.5 아키텍처 미지원 시

```bash
# 최신 vLLM으로 업그레이드
pip install vllm --upgrade

# 또는 소스 빌드
git clone https://github.com/vllm-project/vllm.git
cd vllm && pip install -e .
```

### 시스템 레벨 성능 최적화 (DGX Spark)

GB10 통합 메모리 구조에서는 시스템 메모리 관리가 GPU 성능에 직접 영향을 줌.

**1. swappiness 낮추기 (적용 완료)**

```bash
# 즉시 적용
sudo sysctl vm.swappiness=10

# 영구 적용
echo "vm.swappiness=10" | sudo tee -a /etc/sysctl.d/99-gpu-perf.conf
```

> 기본값 60은 너무 공격적으로 swap을 사용함.
> GB10은 CPU/GPU 통합 메모리이므로 swap 발생 시 GPU 성능 직접 저하.

**2. GPU 클럭 최대 고정 (적용 완료)**

```bash
# 즉시 적용
sudo nvidia-smi -lgc 2418,3003
```

재부팅 시 초기화되므로 systemd 서비스로 영구 등록:

```bash
sudo bash -c 'cat > /etc/systemd/system/nvidia-gpu-clock.service << EOF
[Unit]
Description=Set NVIDIA GPU clock range
After=nvidia-persistenced.service

[Service]
Type=oneshot
ExecStart=/usr/bin/nvidia-smi -lgc 2418,3003
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF'

sudo systemctl daemon-reload
sudo systemctl enable nvidia-gpu-clock.service
```

> GPU 기본 클럭 2457MHz → 최대 3003MHz까지 부스트 허용.

**3. 재부팅 권장**

swap이 이미 꽉 찬 상태에서는 swappiness 변경만으로는 기존 swap 데이터가 정리되지 않음.
재부팅하면 swap이 비워지고 가용 GPU 메모리가 증가하여 `--gpu-memory-utilization`을 더 높일 수 있음.

---

## 11. 실행

```bash
# 시작
cd ~/ws/models && docker compose up -d

# 로그 확인
docker compose logs -f qwen35-27b

# 중지
docker compose down

# 재시작
docker compose restart qwen35-27b
```

> docker-compose 파일: `~/ws/models/docker-compose.yml`
> `restart: unless-stopped` 설정으로 서버 재부팅 시 자동 시작됨.

---

## 12. 참고 링크

- [vLLM 공식 문서](https://docs.vllm.ai)
- [Qwen3.5 HuggingFace](https://huggingface.co/Qwen)
- [NVIDIA NGC PyTorch 컨테이너](https://catalog.ngc.nvidia.com/orgs/nvidia/containers/pytorch)
- [vLLM Grace Hopper 지원 이슈](https://github.com/vllm-project/vllm/issues)
- [scitrera/dgx-spark-vllm (GB10 전용 vLLM)](https://hub.docker.com/r/scitrera/dgx-spark-vllm/tags)
- [lharillo/vllm-blackwell-gb10-spark](https://hub.docker.com/r/lharillo/vllm-blackwell-gb10-spark)
- [DGX Spark vLLM 포럼](https://forums.developer.nvidia.com/t/new-pre-built-vllm-docker-images-for-nvidia-dgx-spark/357832)
- [Qwen3.5-27B on DGX Spark 실행 사례](https://forums.developer.nvidia.com/t/run-qwen3-5-27b-with-spark-vllm-docker/362563)
