# Sprint 4-5: 인덱싱 개선 및 평가 체계 강화

> 목적: 청크 구조 개선(Fact Group, Late Chunking)과 RAG 평가 프레임워크(RAGAS) 설계
> 수정 대상 파일: `codes/embedding/chunker.py`, `codes/embedding/embedder_bgem3.py`, 신규 `codes/eval/`

---

## Part A: Fact Group 청크 (Sprint 4)

### 1. 문제 정의

현재 청크 분포와 검색 특성 (realestate_v2, 6,343문서 / 93,943 청크 기준):

| 청크 타입 | 비율 | 평균 길이 | 검색 특성 |
|-----------|------|----------|----------|
| summary | 6.8% (6,341개) | 300-500 토큰 | 넓은 맥락, 낮은 precision |
| **atomic_fact** | **67.7%** (63,558개) | **50-100 토큰** | **높은 precision, 낮은 recall** |
| hyde | 25.6% (24,044개) | 50-150 토큰 | 질의 매칭 특화 |

> **재색인 후 예상 (11,035문서 전체 색인 시)**:
> - 총 청크: ~134,627 (summary 11,035 + atomic_fact ~83,800 + hyde ~39,792)
> - 문서당 평균 12.2 청크 (실측)
> - Fact Group 추가 시: ~16,000개 fact_group 청크 추가 → 총 ~150,627

문제: atomic_fact가 전체의 2/3를 차지하지만, 각 사실은 너무 짧아서 **하나의 검색에 하나의 측면만** 노출한다. 예를 들어:

```
atomic_fact들:
  "조정대상지역 2주택 취득시 8% 중과"
  "비조정대상지역은 기본세율 1~3% 적용"
  "일시적 2주택은 3년 내 처분 시 중과 제외"
  "법인 취득시 12% 단일 세율"
```

"취득세가 얼마야"라는 질의에 4개 모두 관련 있지만, 검색은 **가장 유사한 1개만** 상위에 올린다. 나머지 3개는 하위로 밀려나거나 아예 top-K에 포함되지 않는다.

> **비유**: 퍼즐 조각(atomic_fact)은 정확하지만, **한 조각만** 보면 전체 그림을 알 수 없다. 여러 조각을 미리 **3-5개씩 묶어놓으면**(fact_group), 한 번의 검색으로 더 완전한 정보를 얻을 수 있다.

### 2. Fact Group 생성 알고리즘

```
문서의 atomic_facts (10-20개)
          │
          ▼
   [의미 유사도 기반 클러스터링]
          │
          ├── 클러스터 1: [fact_1, fact_2, fact_5] → fact_group_1
          ├── 클러스터 2: [fact_3, fact_4] → fact_group_2
          └── 클러스터 3: [fact_6, fact_7, fact_8, fact_9] → fact_group_3
          │
          ▼
   각 클러스터 = 하나의 fact_group 청크
   (summary + "\n" + 클러스터 내 facts 연결)
```

> **핵심 개념 — 클러스터링(Clustering)이란?**
>
> 유사한 데이터끼리 그룹으로 묶는 비지도 학습 기법이다.
>
> **K-Means 알고리즘** (가장 기본적인 클러스터링):
> 1. K개의 중심점을 랜덤 배치
> 2. 각 데이터를 가장 가까운 중심점에 할당
> 3. 중심점을 그룹 평균으로 이동
> 4. 2-3을 수렴할 때까지 반복
>
> **비유**: 학교에서 프로젝트 조를 짤 때, "비슷한 관심사끼리 모여라"고 하면 자연스럽게 그룹이 형성되는 것과 같다. K-Means는 이 과정을 수학적으로 자동화한다.
>
> 여기서는 atomic_fact들의 **임베딩 벡터**가 유사한 것끼리 묶는다. "취득세 8%"와 "취득세 12%"는 임베딩이 비슷하므로 같은 클러스터에, "전세대출 한도"는 다른 클러스터에 들어간다.

### 3. 핵심 코드 — `chunker.py` 수정

```python
import numpy as np
from sklearn.cluster import KMeans


def create_fact_groups(
    facts: list[str],
    embeddings: np.ndarray,      # shape: (N, 1024) — 각 fact의 임베딩
    min_group_size: int = 2,     # 최소 그룹 크기
    max_group_size: int = 5,     # 최대 그룹 크기
    target_groups: int | None = None,  # 목표 그룹 수 (None이면 자동)
) -> list[list[int]]:
    """atomic_fact들을 의미 유사도 기반으로 그룹화.

    Args:
        facts: atomic_fact 텍스트 리스트
        embeddings: 각 fact의 임베딩 벡터 배열
        min_group_size: 최소 그룹 크기 (이보다 작은 그룹은 인접 그룹에 합침)
        max_group_size: 최대 그룹 크기 (이보다 큰 그룹은 분할)
        target_groups: 목표 그룹 수. None이면 N/3으로 자동 설정

    Returns:
        그룹별 fact 인덱스 리스트. 예: [[0, 2, 5], [1, 3], [4, 6, 7, 8]]
    """
    N = len(facts)
    if N <= max_group_size:
        return [list(range(N))]  # 전부 하나의 그룹

    # 목표 그룹 수 자동 결정
    if target_groups is None:
        target_groups = max(2, N // 3)
    target_groups = min(target_groups, N // min_group_size)

    # K-Means 클러스터링
    kmeans = KMeans(n_clusters=target_groups, random_state=42, n_init=10)
    labels = kmeans.fit_predict(embeddings)

    # 라벨별 그룹화
    groups = {}
    for i, label in enumerate(labels):
        groups.setdefault(label, []).append(i)

    # 후처리: 너무 작은 그룹 합치기, 너무 큰 그룹 분할
    result = []
    small_buffer = []

    for group_indices in groups.values():
        if len(group_indices) < min_group_size:
            small_buffer.extend(group_indices)
        elif len(group_indices) > max_group_size:
            # 큰 그룹은 순서대로 max_group_size씩 분할
            for start in range(0, len(group_indices), max_group_size):
                sub = group_indices[start:start + max_group_size]
                if len(sub) >= min_group_size:
                    result.append(sub)
                else:
                    small_buffer.extend(sub)
        else:
            result.append(group_indices)

    # 남은 소규모 facts를 가장 가까운 그룹에 합치기
    if small_buffer:
        if result:
            # 각 남은 fact를 가장 가까운 그룹 중심에 배정
            for idx in small_buffer:
                best_group = 0
                best_sim = -1
                for g, group_indices in enumerate(result):
                    group_center = embeddings[group_indices].mean(axis=0)
                    sim = np.dot(embeddings[idx], group_center) / (
                        np.linalg.norm(embeddings[idx]) * np.linalg.norm(group_center) + 1e-8
                    )
                    if sim > best_sim:
                        best_sim = sim
                        best_group = g
                result[best_group].append(idx)
        else:
            result.append(small_buffer)

    return result


def build_fact_group_text(
    summary: str,
    facts: list[str],
    group_indices: list[int],
) -> str:
    """fact_group 청크의 텍스트 생성.

    구조: [요약 첫 줄] + [그룹 내 facts]
    """
    # 요약의 첫 문장만 헤더로 사용
    summary_header = summary.split(".")[0] + "." if summary else ""

    group_facts = [facts[i] for i in sorted(group_indices)]

    parts = []
    if summary_header:
        parts.append(summary_header)
    parts.extend(f"- {fact}" for fact in group_facts)

    return "\n".join(parts)
```

### 4. chunker.py 통합

```python
# 기존 chunk_v2_document() 함수에 fact_group 타입 추가

def chunk_v2_document(doc: dict, embedder=None) -> list[dict]:
    """v2 문서를 3+1 타입 청크로 분할.

    기존: summary, atomic_fact, hyde
    신규: fact_group (관련 facts 3-5개 묶음)
    """
    chunks = []

    # ... 기존 summary, atomic_fact, hyde 청크 생성 ...

    # fact_group 생성 (임베딩이 필요하므로 embedder가 있을 때만)
    if embedder and len(facts) >= 4:
        # 각 fact의 임베딩 계산
        fact_embeddings = embedder.encode(facts)

        groups = create_fact_groups(
            facts, fact_embeddings,
            min_group_size=2, max_group_size=5,
        )

        for g_idx, group_indices in enumerate(groups):
            group_text = build_fact_group_text(
                summary_text, facts, group_indices,
            )
            chunks.append({
                "chunk_id": f"{doc_id}_fg_{g_idx:03d}",
                "chunk_type": "fact_group",
                "text": group_text,
                "doc_id": doc_id,
                # payload 메타데이터는 atomic_fact와 동일
            })

    return chunks
```

### 5. 기대 효과

| 지표 | 현재 (6,343문서) | 재색인 후 (11,035문서) | + Fact Group 후 |
|------|------|------|------|
| 총 청크 수 | 93,943 | ~134,627 | ~150,627 |
| Overlap@5 | 20% | 25%+ (코퍼스 확대 효과) | **35%+** |
| Overlap@10 | 26% | 32%+ | **40%+** |

> **코퍼스 확대가 Fact Group보다 선행되어야 하는 이유**: 미색인 4,692문서에 자연스러운 구어체 표현이 포함되어 있어 recall 개선의 기본 레버. Fact Group은 이 위에 추가적인 recall 향상을 제공.

---

## Part B: Late Chunking (Sprint 4)

### 1. 알고리즘

```
[기존 방식 — Early Chunking]
문서 → [청크1, 청크2, 청크3] → [embed(청크1), embed(청크2), embed(청크3)]
  각 임베딩은 해당 청크의 단어만 봄 (맥락 없음)

[Late Chunking]
문서 → embed_full(문서 전체) → [토큰1_vec, 토큰2_vec, ..., 토큰N_vec]
  각 토큰 벡터는 문서 전체를 본 후의 맥락화된 벡터
       │
       ▼
  [청크 경계에서 분리 + 평균 풀링]
  청크1_vec = mean(토큰1_vec ~ 토큰K_vec)    ← 문서 맥락 보존!
  청크2_vec = mean(토큰K+1_vec ~ 토큰M_vec)  ← 문서 맥락 보존!
```

> **왜 맥락이 보존되는가?**
>
> 트랜스포머(BERT, BGE-M3 등)의 핵심 메커니즘은 **Self-Attention**이다. 각 토큰이 문서 내 **모든 다른 토큰**과의 관계를 계산한다.
>
> 예: "이 경우 세율은 8%이다"에서 "이 경우"의 임베딩은:
> - Early Chunking: "이 경우"만 보고 임베딩 → "무엇의 경우?"를 모름
> - Late Chunking: 이전 문장 "조정대상지역 2주택 취득시"도 함께 보고 임베딩 → "2주택 취득의 경우"임을 알고 있음

### 2. 핵심 코드 — `embedder_bgem3.py`에 추가

```python
import torch
import numpy as np
from FlagEmbedding import BGEM3FlagModel


def late_chunk_embed(
    model: BGEM3FlagModel,
    full_document: str,
    chunk_texts: list[str],
    max_length: int = 4096,
) -> list[np.ndarray]:
    """Late Chunking: 문서 전체를 임베딩 후 청크별로 분리.

    Args:
        model: BGE-M3 모델 인스턴스
        full_document: 전체 문서 텍스트 (청크들의 원본)
        chunk_texts: 청크 텍스트 리스트 (순서대로)
        max_length: 최대 토큰 수

    Returns:
        각 청크의 임베딩 벡터 리스트 (각 1024D)

    알고리즘:
    1. 전체 문서를 토크나이저로 토큰화
    2. 모델에 통과시켜 토큰별 hidden state 추출
    3. 각 청크의 토큰 범위를 찾아 해당 hidden states를 평균 풀링
    """
    tokenizer = model.tokenizer

    # Step 1: 전체 문서 토큰화
    full_encoding = tokenizer(
        full_document,
        return_tensors="pt",
        max_length=max_length,
        truncation=True,
        return_offsets_mapping=True,   # 토큰 ↔ 문자 위치 매핑
    )

    # Step 2: 모델 통과 → 토큰별 hidden state
    with torch.no_grad():
        outputs = model.model(
            input_ids=full_encoding["input_ids"].to(model.device),
            attention_mask=full_encoding["attention_mask"].to(model.device),
            output_hidden_states=True,
        )

    # 마지막 레이어의 hidden states: shape (1, seq_len, 1024)
    token_embeddings = outputs.hidden_states[-1].squeeze(0).cpu().numpy()
    offset_mapping = full_encoding["offset_mapping"].squeeze(0).tolist()

    # Step 3: 각 청크의 문자 범위 → 토큰 범위 매핑
    chunk_embeddings = []
    current_pos = 0  # full_document 내 현재 위치

    for chunk_text in chunk_texts:
        # 청크가 full_document에서 시작하는 위치 찾기
        chunk_start = full_document.find(chunk_text, current_pos)
        if chunk_start == -1:
            # fallback: 찾지 못하면 독립 임베딩
            chunk_embeddings.append(None)
            continue

        chunk_end = chunk_start + len(chunk_text)
        current_pos = chunk_end

        # 해당 문자 범위에 속하는 토큰 인덱스 찾기
        token_indices = []
        for t_idx, (t_start, t_end) in enumerate(offset_mapping):
            if t_start >= chunk_start and t_end <= chunk_end:
                token_indices.append(t_idx)

        if token_indices:
            # 평균 풀링
            chunk_emb = token_embeddings[token_indices].mean(axis=0)
            # L2 정규화
            chunk_emb = chunk_emb / (np.linalg.norm(chunk_emb) + 1e-8)
            chunk_embeddings.append(chunk_emb)
        else:
            chunk_embeddings.append(None)

    # None인 청크는 독립 임베딩으로 fallback
    for i, emb in enumerate(chunk_embeddings):
        if emb is None:
            fallback = model.encode([chunk_texts[i]])["dense_vecs"][0]
            chunk_embeddings[i] = fallback

    return chunk_embeddings
```

> **`offset_mapping`이란?**
>
> 토크나이저가 텍스트를 토큰으로 분할할 때, 각 토큰이 원본 텍스트의 **어디부터 어디까지**에 해당하는지를 알려주는 매핑이다.
>
> 예: "취득세율" → 토큰 ["취득", "세율"]
> offset_mapping: [(0, 3), (3, 5)]  ← "취득"은 0~3번째 문자, "세율"은 3~5번째 문자

### 3. Late Chunking 적용 조건

| 조건 | Late Chunking | 일반 Chunking | 이유 |
|------|--------------|--------------|------|
| BGE-M3 컬렉션 | O | — | BGE-M3가 Long Context 지원 (8192 토큰) |

> **현재 BGE-M3 컬렉션**: `domain_ontology_v2` (2,146 포인트) + `legal_docs_v2` (976 포인트) = 3,122 포인트.
> Late Chunking은 이 소규모 컬렉션보다 향후 `realestate_v2` 재색인 시 더 큰 효과를 발휘할 수 있다.

| KURE-v1 컬렉션 (realestate_v2) | — | O | KURE-v1(8192 토큰)도 가능하나 11,035문서 전체 재임베딩 비용 큼. 우선 일반 재색인으로 미색인 4,692문서 추가 |
| 문서 길이 < 512토큰 | — | O | 짧은 문서는 맥락 손실이 미미 |
| 문서 길이 > 4096토큰 | 분할 후 적용 | — | GPU 메모리 제약 |

### 4. 인덱싱 파이프라인 수정 — `index_phase2_v2.py`

```python
def index_with_late_chunking(
    entries: list[dict],
    model: BGEM3FlagModel,
    collection: str,
) -> int:
    """Late Chunking을 적용한 인덱싱.

    각 문서(entry)의 전체 텍스트를 한 번에 임베딩한 후,
    청크별로 분리하여 Qdrant에 저장한다.
    """
    total_points = 0

    for entry in entries:
        # 전체 문서 텍스트 조립
        full_text = build_full_document_text(entry)

        # 청크 텍스트 리스트 (chunk_id 순서)
        chunks = split_into_chunks(entry)
        chunk_texts = [c["text"] for c in chunks]

        if len(full_text) > 100:  # 최소 길이 체크
            # Late Chunking 적용
            chunk_embeddings = late_chunk_embed(
                model, full_text, chunk_texts, max_length=4096,
            )
        else:
            # 짧은 문서는 일반 임베딩
            result = model.encode(chunk_texts)
            chunk_embeddings = result["dense_vecs"]

        # Qdrant에 업서트
        for chunk, embedding in zip(chunks, chunk_embeddings):
            # ... upsert 로직 ...
            total_points += 1

    return total_points
```

---

## Part C: RAGAS 평가 프레임워크 (Sprint 5)

> **Phase 2 현재 평가 체계**: 500개 질의 벤치마크(A:150, B:50, C:100, D:100, E:100)에서 P@3 + Avg Top-1 Score + Latency p95를 측정 중. RAGAS는 이 retrieval 메트릭에 **generation 품질 메트릭**을 추가하는 것이다.

### 1. RAGAS 4대 메트릭 설명

```
┌────────────────────────────────────────────────────────┐
│                    RAG 평가 차원                        │
│                                                        │
│   [질의] ──────→ [검색 결과] ──────→ [생성 답변]         │
│                     │                    │              │
│              Context Precision     Faithfulness         │
│              Context Recall        Answer Relevancy     │
│                                                        │
│   검색 품질 ◄──────────────────► 생성 품질              │
└────────────────────────────────────────────────────────┘
```

#### Context Precision (검색 정밀도)

"검색된 청크 중 **관련 있는 것의 비율**이 얼마나 높은가"를 측정한다.

```
검색 결과: [관련O, 관련X, 관련O, 관련X, 관련O]
위치 가중치:  1위에 관련O → 높은 점수
             1위에 관련X → 낮은 점수

계산: precision@k의 가중 평균 (상위에 관련 결과가 많을수록 높음)
```

> **비유**: 구글 검색에서 1페이지(상위 10개)에 관련 결과가 8개면 precision이 높고, 2개면 낮다. 특히 **1위가 관련 있는지**가 가장 중요하다.

#### Context Recall (검색 재현율)

"정답에 필요한 사실이 검색 결과에 **빠짐없이 포함**되었는가"를 측정한다.

```
정답 작성에 필요한 사실: [A, B, C, D]
검색 결과에 포함된 사실: [A, B, D]
누락된 사실: [C]

Context Recall = 3/4 = 0.75
```

#### Faithfulness (충실도)

"생성된 답변의 **모든 주장이 검색 결과에 근거**하는가"를 측정한다.

```
생성된 답변에서 추출된 주장:
  ① "취득세율은 1~3%이다" → 검색 결과에 있음 ✅
  ② "조정대상지역 2주택은 8% 중과" → 검색 결과에 있음 ✅
  ③ "4주택 이상은 15%" → 검색 결과에 없음 ❌ (환각!)

Faithfulness = 2/3 = 0.67
```

> **핵심**: Faithfulness가 낮으면 LLM이 **검색 결과에 없는 내용을 지어내고 있다**는 뜻이다.

#### Answer Relevancy (답변 관련도)

"생성된 답변이 **질문에 맞는 답**인가"를 측정한다.

```
질문: "취득세가 얼마야?"
답변: "취득세는 부동산을 취득할 때 납부하는 세금입니다." → 관련도 낮음 (정의만 설명)
답변: "주택 취득 시 1~3%, 조정대상 2주택 8%" → 관련도 높음 (세율 직접 답변)
```

### 2. RAGAS 설치 및 기본 사용

```bash
# Docker 컨테이너 내 설치
pip install ragas
```

```python
#!/usr/bin/env python3
"""RAGAS 평가 스크립트 — codes/eval/ragas_eval.py"""

from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
)
from datasets import Dataset


def prepare_evaluation_dataset(
    queries: list[str],
    ground_truths: list[str],           # 각 질의의 정답 (수동 작성)
    search_results: list[list[str]],    # 각 질의의 검색 결과 텍스트
    generated_answers: list[str],       # 각 질의의 생성 답변
) -> Dataset:
    """RAGAS 평가용 HuggingFace Dataset 생성.

    RAGAS는 HuggingFace datasets 형식을 요구한다.

    필수 컬럼:
    - question: 사용자 질의
    - answer: 생성된 답변
    - contexts: 검색 결과 리스트
    - ground_truth: 정답 (context_recall 계산용)
    """
    data = {
        "question": queries,
        "answer": generated_answers,
        "contexts": search_results,
        "ground_truth": ground_truths,
    }

    return Dataset.from_dict(data)


def run_evaluation(dataset: Dataset) -> dict:
    """RAGAS 4대 메트릭으로 평가 실행.

    Returns:
        {
            "faithfulness": float,       # 0~1
            "answer_relevancy": float,   # 0~1
            "context_precision": float,  # 0~1
            "context_recall": float,     # 0~1
        }
    """
    result = evaluate(
        dataset,
        metrics=[
            faithfulness,
            answer_relevancy,
            context_precision,
            context_recall,
        ],
    )

    return result


# ─────────────────── 실행 예시 ─────────────────────

if __name__ == "__main__":
    # 테스트 데이터 (실제로는 Adaptive RAG 출력을 수집)
    queries = [
        "1주택자 양도세 비과세 조건은?",
        "취득세 얼마야?",
    ]

    ground_truths = [
        "1세대 1주택자가 2년 이상 보유한 주택을 양도 시 양도소득세 비과세 적용. 조정대상지역은 2년 거주 요건 추가.",
        "주택 취득 시 취득세율은 1~3%(취득가액 기준). 조정대상지역 2주택 8%, 3주택 이상 12% 중과.",
    ]

    search_results = [
        ["1세대 1주택 비과세: 2년 보유 시 비과세...", "조정대상지역 2년 거주 요건..."],
        ["취득세율 1~3%...", "조정대상지역 2주택 8% 중과...", "법인 12%..."],
    ]

    generated_answers = [
        "1세대 1주택자가 2년 이상 보유한 주택을 팔 때 양도소득세가 비과세됩니다. [1]",
        "주택 취득 시 1~3%의 취득세가 부과됩니다. 조정대상지역 2주택은 8% 중과됩니다. [1][2]",
    ]

    dataset = prepare_evaluation_dataset(
        queries, ground_truths, search_results, generated_answers,
    )

    results = run_evaluation(dataset)

    print("=== RAGAS 평가 결과 ===")
    for metric, score in results.items():
        print(f"  {metric}: {score:.4f}")
```

### 3. Ground Truth 구축 전략

RAGAS의 Context Recall은 **정답(ground truth)**이 필요하다. 500개 벤치마크 질의에 대한 정답을 구축하는 방법:

> **활용 가능한 기존 자산**: Phase 2의 500개 벤치마크에는 각 질의에 대한 `expected` 키워드 세트가 이미 존재한다 (`search_test_phase2_v2.py`의 `EXPECTED_RESULTS` dict). 이를 ground truth의 시드로 활용할 수 있다.

| 방법 | 장점 | 단점 | 권장 |
|------|------|------|------|
| 수동 작성 | 최고 품질 | 시간 소모 대 | 핵심 50개 |
| LLM 생성 + 수동 검증 | 빠름, 품질 양호 | 환각 가능 | 나머지 450개 |
| 기존 expected 키워드에서 파생 | 가장 빠름 | 불완전 | 초기 baseline |

```python
# 기존 벤치마크의 expected_keywords에서 ground_truth 자동 생성
def keywords_to_ground_truth(
    query: str,
    expected_keywords: list[str],
) -> str:
    """expected 키워드를 연결하여 간단한 ground truth 생성.

    예: ["취득세", "1~3%", "중과", "8%"]
    → "취득세는 1~3%이며, 중과 시 8%가 적용된다."

    주의: 이 방법은 RAGAS 메트릭의 정확도를 낮출 수 있다.
    정식 평가에는 수동 작성 ground truth를 사용해야 한다.
    """
    return f"{query}에 대한 답변에는 다음 정보가 포함되어야 한다: {', '.join(expected_keywords)}"
```

### 4. 벤치마크 확대 계획

현재: 500개 질의 (A:150, B:50, C:100, D:100, E:100)

확대:

| 세트 | 유형 | 현재 | 추가 | 최종 |
|------|------|------|------|------|

> **현재 500개 벤치마크 결과 (Phase 2 최종)**:
> A:79%, B:60%, C:82%, D:55%, E:55%, 전체:68.0%

| A | 정규 질의 | 150 | +50 | 200 |
| B | 극단 구어체 | 50 | +50 | 100 |
| C | 크로스 도메인 | 100 | +50 | 150 |
| D | 구어체 | 100 | +50 | 150 |
| E | 인터넷 슬랭 | 100 | +50 | 150 |
| **F (신규)** | **네거티브 질의** | 0 | **+50** | **50** |
| **합계** | — | **500** | **+300** | **800** |

> **네거티브 질의(Set F)란?**
>
> 시스템이 "모르겠습니다" 또는 "해당 정보가 없습니다"라고 답해야 하는 질의이다.
>
> 예:
> - "미국 부동산 세금은?" (한국 외 → 범위 벖)
> - "2030년 부동산 전망" (미래 예측 → 근거 없음)
> - "맛집 추천해줘" (도메인 외)
>
> 네거티브 질의에 대해 시스템이 답변을 생성하면 **hallucination**이다. 이를 측정하여 시스템의 "모르는 것을 모른다고 말하는 능력"을 평가한다.

---

## 5. 전체 실행 순서

### Sprint 4-0 (선행: realestate_v2 재색인)

| 단계 | 작업 | 의존 관계 |
|------|------|----------|
| **0-1** | rag_v2/ 11,035문서 전체 재색인 (`index_all.py`) | Qdrant 실행 중 |
| **0-2** | 500개 벤치마크 재실행 → **새 baseline** 측정 | 0-1 |
| **0-3** | 재색인 전후 P@3 비교 (코퍼스 확대 효과 측정) | 0-2 |

> **예상**: 코퍼스 74% 확대(6,343→11,035문서)로 구어체 질의 커버리지 증가.
> YouTube 전문가 스크립트는 자연스러운 구어체 표현을 포함하므로 Set B/D/E에서 +2-5%p 개선 가능.
> 재색인 소요: ~30-50분 (GPU, ~57,000 청크 추가).

### Sprint 4 (인덱싱 개선)

| 단계 | 작업 | 의존 관계 |
|------|------|----------|
| **1** | `chunker.py`에 `create_fact_groups()` 추가 | — |
| **2** | `embedder_bgem3.py`에 `late_chunk_embed()` 추가 | — |
| **3** | 테스트: 10개 문서에 fact_group 생성 + 임베딩 검증 | 1 |
| **4** | Late Chunking 테스트: 10개 문서에 적용 + 코사인 유사도 비교 | 2 |
| **5** | realestate_v2의 다음 배치(notes_rag_todo)에 fact_group 적용 | 3 |
| **6** | BGE-M3 재색인 시 Late Chunking 적용 | 4 |

### Sprint 5 (평가 체계)

| 단계 | 작업 | 의존 관계 |
|------|------|----------|
| **7** | `codes/eval/` 디렉토리 생성, `ragas_eval.py` 작성 | — |
| **8** | ragas 패키지 설치 | — |
| **9** | 핵심 50개 질의 ground truth 수동 작성 | — |
| **10** | LLM으로 나머지 450개 ground truth 생성 + 검증 | 9 |
| **11** | Sprint 3 Adaptive RAG 출력 → RAGAS 평가 실행 | Sprint 3, 10 |
| **12** | 네거티브 질의 50개 추가 | — |

---

## 6. 검증 계획

### Sprint 4 검증

```bash
# Fact Group 효과 측정
# A/B: fact_group 포함/미포함 컬렉션에서 Overlap@5 비교
python3 codes/embedding/quality_eval.py --collection realestate_v2_fg \
    --metric overlap_at_5

# Late Chunking 효과 측정
# 같은 질의에 대해 Early vs Late Chunking의 top-1 cosine similarity 비교
python3 codes/embedding/benchmark_late_chunking.py
```

### Sprint 5 검증

```bash
# RAGAS 4대 메트릭 실행
python3 codes/eval/ragas_eval.py --input sprint3_results.json

# 예상 출력:
# === RAGAS 평가 결과 ===
#   faithfulness: 0.85
#   answer_relevancy: 0.78
#   context_precision: 0.72
#   context_recall: 0.68
```

**최종 목표 지표:**

| 메트릭 | 현재 | 재색인 후 예상 | 최종 목표 | 달성 경로 |
|--------|------|-------------|---------|----------|
| P@3 (검색) | 68.0% | 70-72% | **75%+** | 재색인 + Sprint 1-2 |
| Overlap@5 (검색) | 20% | 25%+ | **40%+** | 재색인 + Sprint 4 Fact Group |
| Faithfulness (생성) | 미측정 | — | **0.85+** | Sprint 3 환각 검사 |
| Answer Relevancy (생성) | 미측정 | — | **0.80+** | Sprint 3 프롬프트 튜닝 |
| Context Precision (검색) | 미측정 | — | **0.75+** | Sprint 1-2 복합 효과 |
| Context Recall (검색) | 미측정 | — | **0.70+** | Sprint 4 Fact Group + Late Chunking |

> **핵심**: realestate_v2 재색인(+4,692문서)만으로 P@3 +2-4%p 개선이 예상된다.
> YouTube 전문가 스크립트에 구어체 표현이 자연스럽게 포함되어 있어 Set B/D/E의 recall이 증가한다.
> 이것이 가장 빠르고 확실한 "저비용 고효과" 개선이며, 다른 Sprint의 선행 조건이다.
