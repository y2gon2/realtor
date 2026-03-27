# `embedder_bgem3.py` — BGE-M3 Triple-Vector Embedder 설계

> 목적: BGE-M3 모델에서 Dense + Sparse + ColBERT 3종 벡터를 동시에 추출하는 임베딩 모듈
> 패턴 원본: `codes/embedding/embedder.py` (KURE-v1 Dense-only embedder)

---

## 1. 기존 `embedder.py`와의 비교

| 항목 | `embedder.py` (기존) | `embedder_bgem3.py` (신규) |
|------|---------------------|---------------------------|
| 모델 | KURE-v1 (SentenceTransformer) | BGE-M3 (BGEM3FlagModel) |
| 출력 벡터 | Dense 1종 (1024D numpy) | Dense + Sparse + ColBERT 3종 |
| 라이브러리 | `sentence-transformers` | `FlagEmbedding` |
| 배치 크기 | 64 (Dense만이므로 메모리 적음) | **32** (ColBERT 출력이 크므로) |
| 용도 | `realestate_v2` 컬렉션 | Phase 2 v2 컬렉션 |

**핵심 원칙**: 기존 `embedder.py`는 **전혀 수정하지 않는다**. 새 파일을 만들어 BGE-M3 전용 embedder로 사용한다.

---

## 2. 주요 개념 설명

### 2-1. Singleton 패턴

> **개념**: 프로그램 전체에서 객체를 **딱 하나만** 생성하고, 이후에는 그 하나를 재사용하는 설계 패턴.

임베딩 모델은 GPU에 로드하는 데 10-15초가 걸린다. 함수를 호출할 때마다 모델을 새로 로드하면 비효율적이다. 따라서 **전역 변수에 한 번만 로드**하고 이후 호출에서는 이미 로드된 모델을 반환한다.

```python
_model = None  # 전역 변수: 처음에는 비어 있음

def _get_model():
    global _model
    if _model is None:           # 아직 로드 안 됐으면
        _model = load_model()    # 로드하고 저장
    return _model                # 이미 로드됐으면 바로 반환
```

### 2-2. FP16 (Half Precision)

> **개념**: 부동소수점 숫자를 32비트가 아닌 16비트로 표현하는 것.

- FP32: 소수점 이하 7자리 정밀도, 4바이트/숫자
- **FP16**: 소수점 이하 3자리 정밀도, **2바이트/숫자**

임베딩 모델은 수억 개의 파라미터를 가진다. FP16을 사용하면:
- GPU 메모리 사용량이 **절반**으로 줄어든다
- 추론 속도가 빨라진다 (GPU의 FP16 연산 유닛이 더 많음)
- 임베딩 품질 차이는 거의 없다 (검색에서 소수점 3자리면 충분)

```python
model = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)  # FP16 사용
```

### 2-3. `max_length` 파라미터

BGE-M3는 최대 **8,192 토큰**까지 입력을 받을 수 있다. 하지만:

- 온톨로지 엔트리는 보통 50-200 토큰
- 법률 문서 청크는 보통 100-500 토큰
- ColBERT는 **토큰 수 × 1024** 크기의 행렬을 출력하므로, 토큰이 많을수록 메모리 사용이 급증

따라서 `max_length=512`로 제한하여 메모리를 절약한다. 512 토큰이면 Phase 2 데이터의 99% 이상을 커버한다.

### 2-4. SparseVector 변환

BGE-M3의 Sparse 출력은 Python `dict`이다:
```python
{12045: 0.832, 4521: 2.301, 8902: 1.100}
# key: 토큰 ID (어휘 사전에서의 인덱스)
# value: 해당 토큰의 중요도 (학습된 가중치)
```

Qdrant에 저장하려면 이것을 `SparseVector` 객체로 변환해야 한다:
```python
SparseVector(
    indices=[4521, 8902, 12045],   # 정렬된 토큰 ID
    values=[2.301, 1.100, 0.832],  # 대응하는 가중치
)
```

---

## 3. 데이터 구조

### 3-1. BGEM3Result 데이터클래스

```python
@dataclass
class BGEM3Result:
    """BGE-M3 임베딩 결과. 3종 벡터를 모두 포함한다."""

    texts: list[str]
    # 입력 텍스트 목록 (임베딩 요청한 원본 텍스트)

    dense_vecs: np.ndarray
    # shape: (N, 1024)
    # 각 텍스트의 Dense 벡터. N은 텍스트 개수.
    # KURE-v1의 EmbeddingResult.embeddings와 동일한 역할.

    sparse_weights: list[dict[int, float]]
    # 길이 N의 리스트. 각 원소는 {token_id: weight} dict.
    # token_id는 BGE-M3 어휘 사전의 인덱스 (0 ~ 250,001).
    # weight는 해당 토큰의 중요도 (0보다 큰 값만 포함).

    colbert_vecs: list[np.ndarray]
    # 길이 N의 리스트. 각 원소는 numpy array.
    # shape: (해당 텍스트의 토큰 수, 1024)
    # 예: 10단어 문장 → (10, 1024), 50단어 문장 → (50, 1024)

    elapsed_sec: float
    # 임베딩 소요 시간 (초)
```

### 3-2. 메모리 사용량 추정

온톨로지 2,146개를 한번에 임베딩할 때 (평균 30 토큰 가정):

| 벡터 종류 | 계산 | 메모리 |
|----------|------|--------|
| Dense | 2,146 × 1,024 × 4B (float32) | ~8.4 MB |
| Sparse | 평균 20개 토큰/엔트리 × (4B + 4B) | ~0.3 MB |
| ColBERT | 2,146 × 30 × 1,024 × 4B | **~264 MB** |

→ ColBERT가 압도적으로 크다. `batch_size=32`로 나눠 처리하면 배치당 ~4MB로 관리 가능.

---

## 4. 함수별 상세 설계

### 4-1. `_get_model()` — 모델 로드 (싱글톤)

```python
_model = None

def _get_model(model_name: str = "BAAI/bge-m3") -> BGEM3FlagModel:
    """BGE-M3 모델을 싱글톤으로 로드한다.

    첫 호출 시 HuggingFace에서 다운로드(~2.3GB) 후 GPU에 로드.
    이후 호출은 캐시된 모델을 반환.

    Args:
        model_name: HuggingFace 모델 ID 또는 로컬 경로.
    """
    global _model
    if _model is None:
        from FlagEmbedding import BGEM3FlagModel
        _model = BGEM3FlagModel(model_name, use_fp16=True)
        print(f"[embedder_bgem3] BGE-M3 로드 완료: {model_name}")
    return _model
```

### 4-2. `embed_texts()` — 배치 임베딩

```python
def embed_texts(
    texts: Sequence[str],
    model_name: str = "BAAI/bge-m3",
    batch_size: int = 32,
    max_length: int = 512,
    return_colbert: bool = True,
) -> BGEM3Result:
    """텍스트 리스트를 BGE-M3로 임베딩하여 3종 벡터를 반환한다.

    내부 동작:
    1. 모델 로드 (싱글톤)
    2. model.encode() 호출 — 3종 벡터를 한번에 생성
    3. 결과를 BGEM3Result로 패킹

    Args:
        texts: 임베딩할 텍스트 리스트.
        batch_size: GPU 배치 크기. ColBERT 때문에 32 권장.
        max_length: 최대 토큰 수. 512이면 Phase 2 데이터 99% 커버.
        return_colbert: False면 ColBERT 벡터 생략 (디버깅용).
    """
```

### 4-3. `to_qdrant_sparse()` — Sparse 변환

```python
def to_qdrant_sparse(weights: dict[int, float]) -> SparseVector:
    """BGE-M3 lexical_weights를 Qdrant SparseVector로 변환한다.

    BGE-M3 출력 형태:
        {12045: 0.832, 4521: 2.301, 8902: 1.100}

    Qdrant 요구 형태:
        SparseVector(indices=[4521, 8902, 12045], values=[2.301, 1.100, 0.832])

    주의: indices는 정렬되어야 하며, values는 indices와 동일 순서.
    """
    if not weights:
        return SparseVector(indices=[], values=[])
    sorted_items = sorted(weights.items())
    return SparseVector(
        indices=[int(k) for k, _ in sorted_items],
        values=[float(v) for _, v in sorted_items],
    )
```

### 4-4. `embed_query()` — 단일 쿼리용 편의 함수

```python
def embed_query(
    text: str,
    model_name: str = "BAAI/bge-m3",
) -> tuple[list[float], SparseVector, list[list[float]]]:
    """단일 쿼리를 임베딩하여 Qdrant API에 바로 전달 가능한 형태로 반환.

    Returns:
        (dense_vector, sparse_vector, colbert_vectors)
        - dense_vector: list[float] (1024개)
        - sparse_vector: SparseVector
        - colbert_vectors: list[list[float]] (토큰수 × 1024)
    """
```

---

## 5. CLI 벤치마크

스크립트를 직접 실행하면(`python embedder_bgem3.py`) 8개의 부동산 도메인 테스트 텍스트로 벤치마크를 수행한다:

```python
if __name__ == "__main__":
    test_texts = [
        "강남구 아파트 매매 실거래가 추이",
        "재건축 초과이익환수제란 무엇인가",
        "DSR 40% 규제가 대출한도에 미치는 영향",
        "경매 낙찰가율이 높은 지역은 어디인가",
        "전세사기 예방을 위한 체크리스트",
        "다주택자 취득세 중과 기준이 어떻게 되나요?",
        "2024년 이후 규제지역 해제 현황",
        "생애최초 주택 구입 시 LTV 우대 조건",
    ]
```

출력 예시:
```
BGE-M3 임베딩 완료: 8건, 2.15s
  Dense shape:    (8, 1024)
  Sparse 평균 토큰 수: 18.3
  ColBERT shape:  8 × (avg 24.5, 1024)
  처리량: 3.7 docs/sec

유사도 매트릭스 (상위 3쌍):
  0.7821: [0] 강남구 아파트... <-> [3] 경매 낙찰가율...
  0.7654: [4] 전세사기... <-> [2] DSR 40%...
```

---

## 6. 전체 코드

아래는 `codes/embedding/embedder_bgem3.py`의 전체 코드이다.

```python
"""
embedder_bgem3.py — BGE-M3 모델로 3종 벡터(Dense+Sparse+ColBERT)를 추출한다.

KURE-v1(embedder.py)이 Dense 벡터만 생성하는 것과 달리,
이 모듈은 FlagEmbedding 라이브러리를 사용하여 3종 벡터를 한번에 추출한다.

Phase 2 v2 컬렉션(domain_ontology_v2, legal_docs_v2) 전용.
realestate_v2 컬렉션은 기존 embedder.py(KURE-v1)를 계속 사용한다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from qdrant_client.models import SparseVector


_model = None  # lazy-loaded singleton


@dataclass
class BGEM3Result:
    """BGE-M3 임베딩 결과."""
    texts: list[str]
    dense_vecs: np.ndarray              # (N, 1024)
    sparse_weights: list[dict[int, float]]
    colbert_vecs: list[np.ndarray]      # list of (num_tokens, 1024)
    elapsed_sec: float


def _get_model(model_name: str = "BAAI/bge-m3"):
    """BGE-M3 모델을 싱글톤으로 로드한다."""
    global _model
    if _model is None:
        from FlagEmbedding import BGEM3FlagModel
        _model = BGEM3FlagModel(model_name, use_fp16=True)
        print(f"[embedder_bgem3] BGE-M3 로드 완료: {model_name}")
    return _model


def embed_texts(
    texts: Sequence[str],
    model_name: str = "BAAI/bge-m3",
    batch_size: int = 32,
    max_length: int = 512,
    return_colbert: bool = True,
) -> BGEM3Result:
    """텍스트 리스트를 BGE-M3로 임베딩하여 3종 벡터를 반환한다."""
    model = _get_model(model_name)
    start = time.time()

    output = model.encode(
        list(texts),
        batch_size=batch_size,
        max_length=max_length,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=return_colbert,
    )

    dense_vecs = np.asarray(output["dense_vecs"])
    sparse_weights = output.get("lexical_weights", [{}] * len(texts))
    colbert_vecs = [
        np.asarray(v) for v in output.get("colbert_vecs", [])
    ] if return_colbert else []

    elapsed = time.time() - start
    return BGEM3Result(
        texts=list(texts),
        dense_vecs=dense_vecs,
        sparse_weights=sparse_weights,
        colbert_vecs=colbert_vecs,
        elapsed_sec=elapsed,
    )


def to_qdrant_sparse(weights: dict[int, float]) -> SparseVector:
    """BGE-M3 lexical_weights를 Qdrant SparseVector로 변환한다."""
    if not weights:
        return SparseVector(indices=[], values=[])
    sorted_items = sorted(weights.items())
    return SparseVector(
        indices=[int(k) for k, _ in sorted_items],
        values=[float(v) for _, v in sorted_items],
    )


def embed_query(
    text: str,
    model_name: str = "BAAI/bge-m3",
) -> tuple[list[float], SparseVector, list[list[float]]]:
    """단일 쿼리를 임베딩하여 Qdrant API에 바로 전달 가능한 형태로 반환한다."""
    result = embed_texts([text], model_name=model_name, batch_size=1)
    dense = result.dense_vecs[0].tolist()
    sparse = to_qdrant_sparse(result.sparse_weights[0])
    colbert = result.colbert_vecs[0].tolist() if result.colbert_vecs else []
    return dense, sparse, colbert


# ---------------------------------------------------------------------------
# CLI: 단독 실행 시 성능 벤치마크
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("  BGE-M3 Triple-Vector Embedder 벤치마크")
    print("=" * 60)

    test_texts = [
        "강남구 아파트 매매 실거래가 추이",
        "재건축 초과이익환수제란 무엇인가",
        "DSR 40% 규제가 대출한도에 미치는 영향",
        "경매 낙찰가율이 높은 지역은 어디인가",
        "전세사기 예방을 위한 체크리스트",
        "다주택자 취득세 중과 기준이 어떻게 되나요?",
        "2024년 이후 규제지역 해제 현황",
        "생애최초 주택 구입 시 LTV 우대 조건",
    ]

    result = embed_texts(test_texts)
    print(f"\nBGE-M3 임베딩 완료: {len(result.texts)}건, {result.elapsed_sec:.2f}s")
    print(f"  Dense shape:    {result.dense_vecs.shape}")
    avg_sparse = sum(len(w) for w in result.sparse_weights) / len(result.sparse_weights)
    print(f"  Sparse 평균 활성 토큰 수: {avg_sparse:.1f}")
    if result.colbert_vecs:
        avg_tokens = sum(v.shape[0] for v in result.colbert_vecs) / len(result.colbert_vecs)
        print(f"  ColBERT shape:  {len(result.colbert_vecs)} × (avg {avg_tokens:.1f}, {result.colbert_vecs[0].shape[1]})")
    print(f"  처리량: {len(result.texts) / result.elapsed_sec:.1f} docs/sec")

    # Dense 유사도 확인
    from numpy.linalg import norm
    embeddings = result.dense_vecs
    sim_matrix = embeddings @ embeddings.T
    pairs = []
    for i in range(len(test_texts)):
        for j in range(i + 1, len(test_texts)):
            pairs.append((sim_matrix[i][j], i, j))
    pairs.sort(reverse=True)
    print("\nDense 유사도 (상위 3쌍):")
    for score, i, j in pairs[:3]:
        print(f"  {score:.4f}: [{i}] {test_texts[i][:30]} <-> [{j}] {test_texts[j][:30]}")

    # Sparse 벡터 예시
    print(f"\nSparse 벡터 예시 (첫 번째 텍스트, 상위 5개 토큰):")
    w = result.sparse_weights[0]
    top5 = sorted(w.items(), key=lambda x: x[1], reverse=True)[:5]
    for tid, weight in top5:
        print(f"  token_id={tid}: weight={weight:.4f}")

    # embed_query 테스트
    print(f"\nembed_query() 테스트:")
    dense, sparse, colbert = embed_query("집 살 때 세금 얼마야")
    print(f"  Dense: {len(dense)}차원")
    print(f"  Sparse: {len(sparse.indices)}개 토큰")
    print(f"  ColBERT: {len(colbert)}개 토큰 × {len(colbert[0]) if colbert else 0}차원")
```

---

## 7. 검증 방법

### 7-1. 컨테이너 내부 실행

```bash
docker exec rag-embedding python3 /workspace/codes/embedding/embedder_bgem3.py
```

### 7-2. 확인 항목

| 항목 | 기대값 |
|------|--------|
| Dense shape | (8, 1024) |
| Sparse 평균 활성 토큰 수 | 15~30 |
| ColBERT shape | 8 × (avg 15~40, 1024) |
| 처리량 | 2~10 docs/sec (첫 실행 시 모델 다운로드 포함하면 느림) |
| embed_query() Dense | 1024차원 |
| embed_query() Sparse | 10~20개 토큰 |
| embed_query() ColBERT | 5~15개 토큰 × 1024차원 |
