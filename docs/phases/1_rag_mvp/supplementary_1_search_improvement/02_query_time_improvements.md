# Sprint 1: Query-Time 검색 개선 — 상세 설계 및 코드

> 목적: 재색인 없이 즉시 적용 가능한 4가지 검색 개선 기법의 알고리즘 설계와 핵심 코드
> 수정 대상 파일: `codes/query/pipeline.py`, `codes/query/analyzer.py`, `codes/query/config.py`, `codes/query/prompts.py`

> **선행 작업: realestate_v2 재색인**
>
> rag_v2 디렉토리에 11,035문서가 있으나 Qdrant에는 6,343문서(93,943 청크)만 색인됨 (3/15 마지막 색인).
> 아래 Sprint 1 기법들을 적용하기 **전에** 재색인을 실행하면 코퍼스 다양성이 74% 증가하여 기본적인 recall이 개선된다.
>
> ```bash
> # Docker 컨테이너에서 실행
> python3 codes/embedding/index_all.py --v2-dir /workspace/rag_v2
> # 예상: ~57,000 청크 추가, 소요 ~30-50분 (GPU)
> ```
>
> 재색인 후 500개 벤치마크를 재실행하여 새 baseline을 측정해야 한다.

---

## 1. Parent Document Retrieval (부모 문서 검색)

### 1-1. 알고리즘

```
사용자 질의 → [기존 SearchPipeline.search()] → top-K 결과 (atomic_fact 등)
                                                     │
                                                     ▼
                                          doc_id 추출 (중복 제거)
                                                     │
                                                     ▼
                                    Qdrant scroll(filter: doc_id in {...})
                                                     │
                                                     ▼
                                    문서별 summary + atomic_facts 수집
                                                     │
                                                     ▼
                                    LLM 컨텍스트로 조립 (검색 결과 + 부모 문서)
```

### 1-2. 핵심 코드 — `pipeline.py`에 추가

```python
def fetch_parent_documents(
    self,
    results: list,           # 검색된 top-K 결과 (Qdrant ScoredPoint)
    collection: str,         # "realestate_v2" 또는 "domain_ontology_v2"
    max_docs: int = 3,       # 상위 몇 개 문서까지 확장
) -> list[dict]:
    """검색 결과의 상위 문서들에 대한 전체 컨텍스트를 반환.

    반환 구조:
    [
        {
            "doc_id": "weolbu_official_20240315_001",
            "summary": "다주택자 취득세 중과에 관한 ...",
            "facts": ["사실1", "사실2", ...],
            "search_score": 0.78,      # 원래 검색 점수
            "matched_chunk_id": "...", # 처음 매칭된 청크 ID
        },
        ...
    ]
    """
    if not results:
        return []

    # Step 1: 상위 결과에서 고유 doc_id 추출 (순서 보존)
    seen = set()
    doc_ids = []
    for point in results:
        doc_id = point.payload.get("doc_id", "")
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            doc_ids.append((doc_id, point))
            if len(doc_ids) >= max_docs:
                break

    # Step 2: 각 doc_id에 대해 summary + atomic_facts 청크 수집
    #
    # 참고: realestate_v2 컬렉션의 v2 문서 구조:
    #   - summary: 1개/문서 (핵심 요지, 300-500 토큰)
    #   - atomic_fact: 5-18개/문서 ("- Fact: ..." 형태)
    #   - hyde: 3-5개/문서 ("- Q: ..." 형태)
    #   - 평균 12.2 청크/문서
    #   - 현재 11,035문서 중 6,343문서만 색인 (재색인 필요)
    #
    parent_docs = []
    for doc_id, original_point in doc_ids:
        # Qdrant scroll로 해당 doc_id의 모든 청크 검색
        chunks, _ = self.qdrant.scroll(
            collection_name=collection,
            scroll_filter={
                "must": [
                    {"key": "doc_id", "match": {"value": doc_id}}
                ]
            },
            limit=100,  # 문서당 최대 100청크 (v2 평균 12.2, 충분)
            with_payload=True,
            with_vectors=False,  # 벡터는 불필요 (payload만 사용)
        )

        summary = ""
        facts = []
        for chunk in chunks:
            chunk_type = chunk.payload.get("chunk_type", "")
            text = chunk.payload.get("text", "")
            if chunk_type == "summary":
                summary = text
            elif chunk_type == "atomic_fact":
                facts.append(text)

        parent_docs.append({
            "doc_id": doc_id,
            "summary": summary,
            "facts": facts,
            "search_score": (
                original_point.score
                if hasattr(original_point, 'score') and original_point.score
                else 0
            ),
            "matched_chunk_id": original_point.id,
        })

    return parent_docs
```

> **핵심 포인트**:
> - `with_vectors=False`로 벡터를 가져오지 않아 네트워크 비용 최소화
> - `scroll` API는 Qdrant의 필터 검색으로, 벡터 유사도 계산 없이 메타데이터만으로 검색
> - 반환된 `parent_docs`는 Sprint 3의 Adaptive RAG Generate 노드에서 LLM 컨텍스트로 사용

### 1-3. PipelineResult 확장

```python
@dataclass
class PipelineResult:
    """검색 파이프라인 전체 결과."""
    ontology_results: list
    legal_results: list
    analysis: QueryAnalysis
    total_latency_ms: float = 0.0
    search_count: int = 0
    parent_documents: list = field(default_factory=list)  # 신규 추가
```

### 1-4. `search()` 메서드에 통합

```python
def search(self, query: str, limit: int = 5,
           fetch_parents: bool = False,  # 신규 파라미터
           parent_collection: str = "realestate_v2",
           **kwargs) -> PipelineResult:
    # ... 기존 검색 로직 ...

    result = PipelineResult(
        ontology_results=onto_final,
        legal_results=legal_final,
        analysis=analysis,
        total_latency_ms=total_latency,
        search_count=search_count,
    )

    # Parent Document Retrieval (옵션)
    if fetch_parents and result.ontology_results:
        result.parent_documents = self.fetch_parent_documents(
            result.ontology_results,
            collection=parent_collection,
            max_docs=3,
        )

    return result
```

---

## 2. Query-Time HyDE (Hypothetical Document Embeddings)

### 2-1. 알고리즘

```
사용자 질의: "집 살 때 세금 얼마야"
          │
          ▼
    [QueryAnalyzer] → type="REWRITE"
          │
          ├─── 경로 A (기존): REWRITE 질의 → "부동산 취득세 납부 의무"
          │
          └─── 경로 B (신규 HyDE): LLM에게 가상 답변 생성 요청
                    │
                    ▼
               "부동산을 매입할 때 취득세가 부과되며, 주택의 경우
                취득가액에 따라 1~3%의 세율이 적용됩니다.
                조정대상지역 다주택자는 8~12%까지 중과됩니다."
                    │
                    ▼
               [BGE-M3 임베딩] → 1024D 벡터
                    │
                    ▼
               [Qdrant 검색] → HyDE 검색 결과
                    │
                    ▼
          [RRF 합산]: 원본(1.0) + REWRITE(0.8) + HyDE(0.7)
```

### 2-2. HyDE 프롬프트 — `prompts.py`에 추가

```python
HYDE_PROMPT_TEMPLATE = """당신은 대한민국 부동산 전문가입니다.

아래 질문에 대한 답변을 2~3문장으로 작성하세요.
정확하지 않아도 괜찮습니다. 핵심 전문용어를 포함하는 것이 중요합니다.

질문: {query}

답변:"""
```

> **설계 의도**: 프롬프트가 짧고 단순한 이유는, HyDE의 목적이 **정확한 답변이 아니라 전문 용어를 포함한 텍스트를 생성**하는 것이기 때문이다. 복잡한 프롬프트는 오히려 불필요한 내용을 생성하여 임베딩 품질을 저하시킬 수 있다.

> **Phase 2 CRAG와의 관계**: CRAG(`compensator.py`)가 이미 검색 결과를 CORRECT/AMBIGUOUS/INCORRECT로 평가하고 AMBIGUOUS/INCORRECT 시 LLM이 정규 용어를 제안하여 재검색한다. HyDE는 이와 다른 접근: CRAG는 검색 **후** 보정이지만, HyDE는 검색 **전** 질의를 강화한다. 둘은 보완적이다.

### 2-3. Analyzer 확장 — `analyzer.py`

```python
def generate_hyde_document(self, query: str) -> str | None:
    """REWRITE 질의에 대한 가상 답변 문서 생성.

    HyDE(Hypothetical Document Embeddings) 기법:
    사용자 질의 대신 가상 답변을 임베딩하여 검색하면,
    질의-문서 간 어휘 격차를 줄일 수 있다.

    Returns:
        가상 답변 문서 (2-3문장) 또는 실패 시 None
    """
    from prompts import HYDE_PROMPT_TEMPLATE

    prompt = HYDE_PROMPT_TEMPLATE.format(query=query)

    try:
        hyde_doc = self._call_claude_cli(prompt)
        # 너무 짧거나 긴 응답 필터링
        if len(hyde_doc) < 20 or len(hyde_doc) > 500:
            return None
        return hyde_doc.strip()
    except Exception as e:
        print(f"[HyDE] 가상 문서 생성 실패: {e}")
        return None
```

> **왜 별도 LLM 호출인가?**
>
> REWRITE 단계에서 이미 LLM을 호출하므로, HyDE 호출은 추가 비용이다. 하지만 두 호출의 목적이 다르다:
> - REWRITE: 구어체 → 정규 질의 형태로 변환 (짧은 질의)
> - HyDE: 가상 답변 문서 생성 (긴 문서, 풍부한 전문 용어)
>
> 최적화: REWRITE와 HyDE를 **하나의 LLM 호출로 통합**할 수 있다. 프롬프트에 "1) 정규화된 질의, 2) 가상 답변"을 함께 요청하면 API 호출 1회로 둘 다 얻을 수 있다.

### 2-4. Pipeline 통합 — `pipeline.py`

```python
# search() 메서드의 Step 4 (REWRITE/DECOMPOSE) 확장

# Step 4-B (신규): HyDE 검색 (REWRITE일 때만)
hyde_onto_hits = []
hyde_legal_hits = []

if analysis.type == "REWRITE":
    hyde_doc = self.analyzer.generate_hyde_document(query)
    if hyde_doc:
        hyde_dense, hyde_sparse, hyde_colbert = embed_query(hyde_doc)

        if not search_legal_only:
            hyde_onto_hits = search_ontology(
                self.qdrant, ONTOLOGY_COLLECTION,
                hyde_dense, hyde_sparse, hyde_colbert,
                mode=SEARCH_MODE, limit=fetch_limit,
            )
            search_count += 1

        if not search_ontology_only:
            hyde_legal_hits = search_legal(
                self.qdrant, LEGAL_COLLECTION,
                hyde_dense, hyde_sparse, hyde_colbert,
                mode=SEARCH_MODE, limit=fetch_limit,
            )
            search_count += 1

# Step 5: RRF 합산 (원본 + REWRITE + HyDE)
if analysis.type == "REWRITE" and hyde_onto_hits:
    # 3-way RRF: [원본, REWRITE, HyDE]
    weights = [
        ORIGINAL_WEIGHT_REWRITE,       # 1.0
        TRANSFORMED_WEIGHT_REWRITE,     # 0.8
        HYDE_WEIGHT_REWRITE,            # 0.7 (신규 상수)
    ]
    onto_lists = [orig_onto] + trans_onto_lists + [hyde_onto_hits]
    onto_final = rrf_merge(onto_lists, weights=weights)[:rrf_limit]
else:
    # 기존 로직 유지
    onto_final = rrf_merge(
        [orig_onto] + trans_onto_lists, weights=weights
    )[:rrf_limit]
```

### 2-5. `config.py`에 추가할 상수

```python
# ────────────── HyDE 설정 ──────────────────────
HYDE_ENABLED = True                    # HyDE 활성화 여부
HYDE_WEIGHT_REWRITE = 0.7             # HyDE 결과의 RRF 가중치
HYDE_MAX_LENGTH = 500                  # 가상 답변 최대 길이 (자)
HYDE_MIN_LENGTH = 20                   # 가상 답변 최소 길이 (자)
```

---

## 3. RAG-Fusion: Multi-Query 생성 확장

### 3-1. 알고리즘

```
사용자 질의: "집 살 때 세금 얼마야"
          │
          ▼
    [QueryAnalyzer] → type="REWRITE"
          │
          ▼ (현재: 변환 질의 1개)
    "부동산 취득세 납부 의무"

          │
          ▼ (RAG-Fusion: 변환 질의 3-5개)
    ① "부동산 취득세 납부 의무"
    ② "주택 구입 시 세금 종류와 세율"
    ③ "아파트 매매 취득세 계산 방법"
    ④ "부동산 매수 과세 항목"
          │
          ▼
    각각 독립적으로 검색 → RRF 합산
```

### 3-2. 프롬프트 수정 — `prompts.py`

현재 REWRITE 프롬프트의 출력 형식을 확장한다:

```python
# 기존 프롬프트 (REWRITE 시 queries 배열에 1개)
# → 수정: 3-5개 변형 질의 생성 지시

# USER_PROMPT_TEMPLATE 내 수정 부분:
RAG_FUSION_INSTRUCTION = """
## REWRITE 시 추가 규칙
- REWRITE로 판정한 경우, queries 배열에 **3~5개**의 변형 질의를 생성하세요.
- 각 변형은 같은 의미를 다른 표현/관점으로 표현해야 합니다.
- 변형 전략:
  1. 전문용어로 정규화
  2. 동의어/유의어 사용
  3. 구체적 상황으로 변환
  4. 상위 개념으로 확장
- 예시:
  원본: "집 살 때 세금 얼마야"
  queries: [
    {"query": "부동산 취득세 납부 의무", "domain_hint": "tax"},
    {"query": "주택 구입 시 취득세율 계산", "domain_hint": "tax"},
    {"query": "아파트 매매 세금 종류", "domain_hint": "tax"},
    {"query": "부동산 매수 시 과세 항목 및 세율", "domain_hint": "tax"}
  ]
"""
```

### 3-3. `_compute_weights()` 수정 — `pipeline.py`

```python
def _compute_weights(analysis_type: str, num_sub_queries: int) -> list[float]:
    """RRF 가중치: [원본, 변환1, 변환2, ...]."""
    if analysis_type == "REWRITE":
        # RAG-Fusion: 원본(1.0) + 첫 번째 변환(0.8) + 나머지(0.6)
        weights = [ORIGINAL_WEIGHT_REWRITE, TRANSFORMED_WEIGHT_REWRITE]
        # 추가 변환 질의에는 감소된 가중치 적용
        for i in range(num_sub_queries - 1):
            weights.append(ADDITIONAL_REWRITE_WEIGHT)  # 0.6
        return weights
    elif analysis_type == "DECOMPOSE":
        return [ORIGINAL_WEIGHT_DECOMPOSE] + \
               [SUB_QUERY_WEIGHT_DECOMPOSE] * num_sub_queries
    return [1.0]
```

### 3-4. `config.py`에 추가할 상수

```python
# ────────────── RAG-Fusion 설정 ────────────────
RAG_FUSION_ENABLED = True              # Multi-Query 활성화 여부
MAX_REWRITE_QUERIES = 5                # REWRITE 시 최대 변형 질의 수
ADDITIONAL_REWRITE_WEIGHT = 0.6        # 2번째 이후 변형 질의의 RRF 가중치
```

> **비용/레이턴시 영향**:
> - LLM 호출: 변화 없음 (기존 1회에서 출력만 확장)
> - 임베딩: +2-4회 (변형 질의 수만큼)
> - Qdrant 검색: +2-4회
> - 추가 레이턴시: ~100-200ms (임베딩 + 검색이 병렬화 가능하면 최소화)

---

## 4. Dynamic Alpha Tuning (동적 α 가중치)

### 4-1. 알고리즘

> **현재 상태 (Phase 2A 완료)**
>
> Query-type별 4개 버킷 α가 이미 구현되어 운영 중:
> - `SIMPLE_FORMAL`: 0.7 (정규 용어 2+ → CE 신뢰)
> - `SIMPLE_MIXED`: 0.5 (정규 용어 1개)
> - `REWRITE`: 0.4 (구어체 변환 → RRF 비중↑)
> - `COLLOQUIAL_OVERRIDE`: 0.3 (극단 구어체 → CE 비중 최소)
>
> 아래 Dynamic Alpha는 이 4개 버킷을 **연속적 회귀 모델**로 발전시키는 방안이다.

```
질의 특성 추출:
  x1 = colloquial_score (0~5, 구어체 정도)
  x2 = matched_terms_count (0~N, 매칭된 전문용어 수)
  x3 = query_length (자 수)
  x4 = domain_count (감지된 도메인 수)
       │
       ▼
  [회귀 모델] → α_predicted (0.0 ~ 1.0)
       │
       ▼
  final_score = α_predicted × rrf_rank_score + (1 - α_predicted) × ce_score
```

> **핵심 개념 — 회귀 모델(Regression Model)이란?**
>
> 입력 변수(x)로부터 연속적인 출력 값(y)을 예측하는 모델이다.
>
> **선형 회귀** 예시:
> ```
> α = w1 × colloquial_score + w2 × matched_terms + w3 × query_length + w4 × domain_count + bias
> ```
>
> 여기서 w1, w2, w3, w4, bias는 훈련 데이터로부터 학습된다.
>
> **비유**: "기온, 습도, 풍속으로 내일 날씨를 예측"하는 것처럼, "질의 특성으로 최적 α를 예측"한다.

### 4-2. 훈련 데이터 수집 스크립트

500개 벤치마크 질의에 대해 다양한 α 값을 시도하여 최적 α를 찾는다:

```python
#!/usr/bin/env python3
"""Dynamic Alpha 훈련 데이터 수집.

500개 벤치마크 질의 × 11개 α값(0.0~1.0, 0.1 간격) →
각 질의에 대한 최적 α 기록.
"""

import json
import numpy as np
from pathlib import Path

# 가정: benchmark_results.json에 각 (query, alpha) 조합의 P@3 결과가 있음
# 형식: [{"query": "...", "alpha": 0.3, "p_at_3": 1, "features": {...}}, ...]

def find_optimal_alphas(benchmark_file: str) -> list[dict]:
    """각 질의에 대한 최적 α와 특성 추출."""
    with open(benchmark_file) as f:
        results = json.load(f)

    # 질의별 그룹화
    by_query = {}
    for r in results:
        q = r["query"]
        if q not in by_query:
            by_query[q] = []
        by_query[q].append(r)

    training_data = []
    for query, runs in by_query.items():
        # P@3이 가장 높은 α 선택 (동점이면 α=0.5에 가까운 것)
        best = max(runs, key=lambda r: (r["p_at_3"], -abs(r["alpha"] - 0.5)))

        training_data.append({
            "features": best["features"],  # {cs, mt, ql, dc}
            "optimal_alpha": best["alpha"],
        })

    return training_data


def train_alpha_model(training_data: list[dict]):
    """sklearn LinearRegression으로 α 예측 모델 학습."""
    from sklearn.linear_model import Ridge
    from sklearn.model_selection import cross_val_score
    import pickle

    X = np.array([
        [d["features"]["colloquial_score"],
         d["features"]["matched_terms_count"],
         d["features"]["query_length"],
         d["features"]["domain_count"]]
        for d in training_data
    ])
    y = np.array([d["optimal_alpha"] for d in training_data])

    # Ridge Regression (L2 정규화로 과적합 방지)
    model = Ridge(alpha=1.0)

    # 5-fold Cross Validation
    scores = cross_val_score(model, X, y, cv=5, scoring="neg_mean_squared_error")
    print(f"CV MSE: {-scores.mean():.4f} ± {scores.std():.4f}")

    model.fit(X, y)
    print(f"계수: cs={model.coef_[0]:.3f}, mt={model.coef_[1]:.3f}, "
          f"ql={model.coef_[2]:.3f}, dc={model.coef_[3]:.3f}")
    print(f"절편: {model.intercept_:.3f}")

    # 모델 저장
    model_path = Path("codes/query/alpha_model.pkl")
    with open(model_path, "wb") as f:
        pickle.dump(model, f)
    print(f"모델 저장: {model_path}")

    return model
```

> **Ridge Regression을 선택한 이유**:
>
> 500개 데이터에 4개 특성이므로 단순 선형 회귀로도 충분하다. Ridge는 L2 정규화를 추가하여 특성 간 상관관계가 있을 때(예: colloquial_score와 matched_terms_count는 역상관) 안정적인 예측을 보장한다.

### 4-3. `_resolve_alpha()` 수정 — `pipeline.py`

```python
import pickle
from pathlib import Path

class SearchPipeline:
    def __init__(self, ...):
        # ... 기존 초기화 ...

        # Dynamic Alpha 모델 로딩 (있으면)
        self._alpha_model = None
        model_path = Path(__file__).parent / "alpha_model.pkl"
        if model_path.exists():
            with open(model_path, "rb") as f:
                self._alpha_model = pickle.load(f)
            print("[SearchPipeline] Dynamic Alpha 모델 로드 완료")

    def _resolve_alpha(self, analysis: QueryAnalysis, query: str) -> float:
        """질의 분석 결과에 따라 최적 α 결정.

        우선순위:
        1. Dynamic Alpha 모델 (학습됨) — 연속 예측
        2. 구어체 점수 override — 극단 구어체 보호
        3. 질의 유형별 고정 α — fallback
        """
        cs = self.analyzer._colloquial_score(query)

        # 극단 구어체는 항상 override (안전장치)
        if cs >= 3:
            return ALPHA_COLLOQUIAL_OVERRIDE  # 0.3

        # Dynamic Alpha 모델 사용 (있으면)
        if self._alpha_model is not None:
            import numpy as np
            matched = self.analyzer._find_matching_terms(query)
            domains = self.analyzer._detect_domains(query)

            features = np.array([[
                cs,
                len(matched),
                len(query),
                len(domains),
            ]])

            alpha = float(self._alpha_model.predict(features)[0])
            # 범위 클램핑 (0.2 ~ 0.8)
            return max(0.2, min(0.8, alpha))

        # Fallback: 기존 고정 α
        if analysis.type == "SIMPLE":
            matched = self.analyzer._find_matching_terms(query)
            if len(matched) >= 2:
                return ALPHA_BY_QUERY_TYPE["SIMPLE_FORMAL"]
            return ALPHA_BY_QUERY_TYPE["SIMPLE_MIXED"]

        return ALPHA_BY_QUERY_TYPE.get(analysis.type, 0.5)
```

---

## 5. 실행 순서

| 단계 | 작업 | 의존 관계 |
|------|------|----------|
| **1** | `config.py`에 HyDE/RAG-Fusion 상수 추가 | — |
| **2** | `prompts.py`에 HyDE 프롬프트 + RAG-Fusion 지시 추가 | — |
| **3** | `analyzer.py`에 `generate_hyde_document()` 추가 | 2 |
| **4** | `pipeline.py`에 `fetch_parent_documents()` 추가 | — |
| **5** | `pipeline.py`의 `search()`에 HyDE + RAG-Fusion + Parent Doc 통합 | 1, 2, 3, 4 |
| **6** | 25개 질의 스모크 테스트 | 5 |
| **7** | 500개 벤치마크 실행 (HyDE ON/OFF, RAG-Fusion ON/OFF ablation) | 6 |
| **8** | Dynamic Alpha 훈련 데이터 수집 (α 그리드 서치) | 7 |
| **9** | α 회귀 모델 학습 + `_resolve_alpha()` 교체 | 8 |
| **10** | 최종 500개 벤치마크 재실행 | 9 |

---

## 6. 기대 효과 및 검증

### 6-1. 기법별 기대 효과

| 기법 | 주요 영향 세트 | 기대 P@3 개선 | 추가 레이턴시 | 추가 비용/질의 |
|------|--------------|-------------|-------------|--------------|
| Parent Doc | Generation 품질 | 직접 P@3 영향 없음 | ~20ms | 무시 |
| Query-Time HyDE | Set B/D (구어체) | +5-8% | ~2-3초 (LLM) | ~$0.003 |
| RAG-Fusion | Set B/D/E | +5-10% | ~100-200ms | 무시 |
| Dynamic α | 전체 | +3-5% | 무시 | 무시 |
| 슬랭 쿼리 확장 | Set E (슬랭) | **이미 적용** (+2%p 달성) | 무시 | 무시 |

### 6-2. 벤치마크 비교 계획

```bash
# Step 1: Baseline 기록 (68.0%)
python3 codes/embedding/benchmark_phase2_v2.py --setting C > baseline.json

# Step 2: HyDE만 켜고
python3 codes/embedding/benchmark_phase2_v2.py --setting C --hyde > hyde_only.json

# Step 3: RAG-Fusion만 켜고
python3 codes/embedding/benchmark_phase2_v2.py --setting C --rag-fusion > fusion_only.json

# Step 4: HyDE + RAG-Fusion
python3 codes/embedding/benchmark_phase2_v2.py --setting C --hyde --rag-fusion > both.json

# Step 5: + Dynamic Alpha
python3 codes/embedding/benchmark_phase2_v2.py --setting C --hyde --rag-fusion --dynamic-alpha > final.json
```

### 6-3. 위험 요소

| 위험 | 확률 | 영향 | 대응 |
|------|------|------|------|
| HyDE가 잘못된 전문용어 생성 | 중 | 검색 결과 오염 | 원본 질의 가중치(1.0)가 항상 포함되므로 회귀 제한적 |
| RAG-Fusion이 중복 결과만 생성 | 저 | 효과 미미 | RRF 특성상 중복 결과는 순위만 강화, 손해 없음 |
| Dynamic α 과적합 | 중 | 벤치마크에만 최적화 | 5-fold CV로 검증, Ridge 정규화 적용 |
| LLM 호출 레이턴시 | 고 | 사용자 대기 시간 증가 | REWRITE+HyDE 통합 프롬프트로 호출 1회로 축소 |
