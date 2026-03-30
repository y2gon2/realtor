# Step 1 — 하이브리드 전략 (원본 + 변환 동시 검색)

> 작성일: 2026-03-28
> 선행 문서: `01_sequential_improvement_plan.md` §2, `02_execution_overview.md`
> 목적: 원본 질의와 변환 질의를 동시에 검색하여 Weighted RRF로 합산, 변환 회귀 방지
> 수정 파일: `codes/query/pipeline.py`, `codes/query/config.py`, `codes/query/merger.py`
> 상태: **구현 완료**, 벤치마크 실행 대기

---

## 0. 문제 정의

### 0-1. 현재 흐름 vs 개선 흐름

```
[현재 — 변환 질의 단독 검색]
Query → LLM 변환 → 변환된 질의만 검색 → 결과
  문제: 변환이 잘못되면 원본보다 나빠짐

[개선 — 원본 + 변환 동시 검색]
Query → LLM 변환 → 변환된 질의 검색 ─┐
  │                                    ├→ Weighted RRF 합산 → Top-K
  └──────────→ 원본 질의도 검색 ───────┘
  보험: 변환이 잘못되어도 원본이 살아 있음
```

> **쉬운 비유 — 통역사와 원본 동시 제출:**
>
> 외국어 서류를 관공서에 제출할 때, **번역본만** 내면 번역 오류 시 처리가 잘못될 수 있다.
> **원본 + 번역본을 함께** 제출하면, 번역이 틀려도 원본이 보험 역할을 한다.
> 이것이 하이브리드 전략의 핵심이다.

### 0-2. 42개 실측 증거

| 문제 유형 | 건수 | 사례 |
|----------|------|------|
| REWRITE 회귀 | 2건 | "양도세 비과세" → "1세대 1주택 비과세"로 변환 시 "양도세" 소실 |
| DECOMPOSE 회귀 | 5건 | "재건축+양도세"를 분해하면 인과관계 소실 |

→ 원본을 항상 검색에 포함하면 이 7건의 회귀를 **구조적으로 방지**할 수 있다.

---

## 1. 이론적 배경 — 외부 연구

### 1-1. RAG-Fusion (Raudaschl, 2023)

- **핵심**: 원본 + N개 변형 질의를 모두 검색 후 RRF(Reciprocal Rank Fusion) 합산
- **정량 결과**: 단일 질의 대비 Recall@K 5~15% 향상 (다수 벤치마크)
- **핵심 발견**: 변형 수는 4~5개를 넘으면 수확 체감. **원본 질의를 항상 포함**하는 것이 필수
- 출처: https://github.com/Raudaschl/rag-fusion

### 1-2. HyDE + Original Blend (Gao et al., ACL 2023)

- **논문**: "Precise Zero-Shot Dense Retrieval without Relevance Labels"
- **핵심**: LLM이 가설 문서(Hypothetical Document)를 생성 → 임베딩하여 검색. 원본 병행 시 추가 +2~3%
- **정량**: BEIR 벤치마크 nDCG +7~12%
- 출처: https://arxiv.org/abs/2212.10496

### 1-3. Query2Doc (Wang et al., EMNLP 2023)

- **논문**: "Query2doc: Query Expansion with Large Language Models"
- **핵심**: LLM 생성 pseudo-document를 원본 질의와 결합. BM25에서 원본 5× 반복하여 키워드 보존
- **정량**: MS MARCO에서 BM25 3~15% 향상
- 출처: https://aclanthology.org/2023.emnlp-main.585/

### 1-4. RRF 원 논문 (Cormack, Clarke & Buettcher, 2009)

- **논문**: "Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods"
- **핵심**: k=60이 TREC 벤치마크에서 최적
- 출처: University of Waterloo, SIGIR 2009

### 1-5. Scaling RAG Fusion — **경고** (2026.03)

- **핵심 경고**: re-ranking 적용 환경에서 RAG Fusion 효과가 소멸하거나 Hit@10이 오히려 하락
- **대응**: Step 5(CE 재도입) 시 가중치를 재조정해야 함. Step 1에서는 re-ranking 없이 순수 RRF만 적용
- 출처: https://arxiv.org/abs/2603.02153

---

## 2. RRF(Reciprocal Rank Fusion)란?

> **쉬운 비유 — 여러 심사위원의 종합 순위:**
>
> 노래 오디션에서 심사위원 3명이 각각 참가자에게 순위를 매긴다.
> "종합 순위"를 계산할 때, **순위가 높을수록 더 큰 점수**를 주어 합산한다.
> 이것이 RRF(Reciprocal Rank Fusion)이다.
>
> 예를 들어 참가자 A가 심사위원 1에게 1위, 심사위원 2에게 3위를 받으면:
> - 심사위원 1 기여: 1/(60+1) = 0.0164
> - 심사위원 2 기여: 1/(60+3) = 0.0159
> - 합계: 0.0323
>
> 여기서 60은 "k값"이라 하며, 순위 차이의 민감도를 조절하는 상수이다.

### 수식

```
RRF_score(doc) = Σᵢ  wᵢ × 1/(k + rankᵢ(doc) + 1)

여기서:
- wᵢ: i번째 검색 리스트의 가중치 (원본 / 변환 / 서브 질의)
- k = 60 (RRF 상수, 원 논문 권장값)
- rankᵢ(doc): i번째 리스트에서 doc의 순위 (0부터 시작)
- 리스트에 없는 doc의 기여는 0
```

> **k 파라미터의 의미:**
>
> k가 클수록 순위 차이에 둔감해진다 (1위와 10위의 점수 차이가 줄어듦).
> k가 작으면 상위 순위에 집중한다. k=60은 "상위도 중요하지만 하위 순위의 기여도 무시하지 않는" 균형점이다.

---

## 3. 가중치 설계 (config.py)

> **쉬운 비유 — 위원회 투표:**
>
> 원본 질의 = **선임 위원** (경력 10년): 가중치 높음, 이미 검증된 결과
> 변환 질의 = **신임 위원** (경력 1년): 가중치 낮음, 새로운 관점 제공
> 두 위원의 투표를 합치되, 선임 위원의 의견에 더 큰 가중치를 준다.

### 3-1. 가중치 상수 (config.py L88~94)

```python
# ─────────────────────────── 하이브리드 전략 가중치 ───────────
# P1-a-1: 원본 + 변환 질의 동시 검색 시 RRF 가중치

ORIGINAL_WEIGHT_REWRITE = 1.0       # REWRITE 시 원본 질의 가중치
TRANSFORMED_WEIGHT_REWRITE = 0.8    # REWRITE 시 변환 질의 가중치
ORIGINAL_WEIGHT_DECOMPOSE = 1.2     # DECOMPOSE 시 원본 질의 가중치
SUB_QUERY_WEIGHT_DECOMPOSE = 0.6    # DECOMPOSE 시 서브 질의 가중치 (각각)
```

### 3-2. 가중치 근거

| 파라미터 | 값 | 근거 |
|---------|---|------|
| ORIGINAL_WEIGHT_REWRITE = 1.0 | 높음 | 정규 질의 79.3% 성공 → 원본이 이미 유효 |
| TRANSFORMED_WEIGHT_REWRITE = 0.8 | 중간 | 변환은 보조 신호. 과잉 변환 시 원본이 우세 |
| ORIGINAL_WEIGHT_DECOMPOSE = 1.2 | 최고 | DECOMPOSE 회귀 5건 → 원본 가중치 2배 강화 |
| SUB_QUERY_WEIGHT_DECOMPOSE = 0.6 | 낮음 | 서브 질의는 보조. 0.6 × 2~3개 = 1.2~1.8 총합이 원본 1.2와 균형 |

---

## 4. 검색 흐름 변경 (pipeline.py)

### 4-1. 유형별 검색 흐름

```
[SIMPLE — 변경 없음]
Query → 원본 검색 → 결과 (weight 1.0)

[REWRITE — 2중 검색]
Query → 원본 검색 ──────────────────→ 결과 A (weight 1.0) ─┐
  └── LLM 변환 → 변환 질의 검색 ──→ 결과 B (weight 0.8) ──┤
                                                             └→ Weighted RRF → Top-K

[DECOMPOSE — 3중+ 검색]
Query → 원본 검색 ──────────────────→ 결과 A (weight 1.2) ─┐
  ├── LLM 분해 → 서브 질의 1 검색 → 결과 B (weight 0.6) ──┤
  └── 서브 질의 2 검색 ────────────→ 결과 C (weight 0.6) ──┤
                                                             └→ Weighted RRF → Top-K
```

### 4-2. _compute_weights() 함수 (pipeline.py L47~53)

```python
def _compute_weights(analysis_type: str, num_sub_queries: int) -> list[float]:
    """RRF 가중치: [원본, 변환1, 변환2, ...].

    분석 유형에 따라 원본과 변환 질의의 가중치를 반환한다.
    리스트의 첫 요소는 항상 원본 질의의 가중치이고,
    나머지는 변환/서브 질의의 가중치이다.
    """
    if analysis_type == "REWRITE":
        return [ORIGINAL_WEIGHT_REWRITE, TRANSFORMED_WEIGHT_REWRITE]
    elif analysis_type == "DECOMPOSE":
        return [ORIGINAL_WEIGHT_DECOMPOSE] + [SUB_QUERY_WEIGHT_DECOMPOSE] * num_sub_queries
    return [1.0]
```

### 4-3. search() 핵심 변경 (pipeline.py L119~239)

파이프라인의 핵심 흐름 (6단계):

```python
def search(self, query, limit=5, rerank=False, ...):
    # Step 1: 질의 분석 (QueryAnalyzer)
    analysis = self.analyzer.analyze(query)

    # Step 2: 원본 질의 항상 검색 (하이브리드의 핵심)
    orig_dense, orig_sparse, orig_colbert = embed_query(query)
    orig_onto = search_ontology(self.qdrant, ..., orig_dense, orig_sparse, ...)

    # Step 3: SIMPLE이면 원본 결과만 반환
    if analysis.type == "SIMPLE":
        return PipelineResult(ontology_results=orig_onto[:limit], ...)

    # Step 4: REWRITE/DECOMPOSE — 변환 질의도 검색
    trans_onto_lists = []
    for sub_q in analysis.queries:
        dense, sparse, colbert = embed_query(sub_q.query)
        onto_hits = search_ontology(self.qdrant, ..., dense, sparse, ...)
        trans_onto_lists.append(onto_hits)

    # Step 5: Weighted RRF 합산 (원본 + 변환)
    weights = _compute_weights(analysis.type, len(analysis.queries))
    onto_final = rrf_merge([orig_onto] + trans_onto_lists, weights=weights)[:limit]

    # Step 6: (선택) Cross-Encoder 리랭킹
    if rerank:
        onto_final = self._rerank_ontology(query, onto_final, ...)

    return PipelineResult(ontology_results=onto_final, ...)
```

---

## 5. RRF 병합 함수 (merger.py)

> **쉬운 비유 — 선거 개표:**
>
> 각 투표소(검색 리스트)에서 후보(문서)에게 순위를 매기고,
> 중앙선관위(RRF 함수)가 가중치를 적용하여 전국 종합 순위를 계산한다.

```python
def rrf_merge(
    result_lists: list[list],
    k: int = 60,
    weights: list[float] | None = None,
) -> list:
    """N개의 검색 결과 리스트를 Weighted RRF로 합산.

    Args:
        result_lists: 서브 질의별 Qdrant 검색 결과.
        k: RRF 파라미터 (기본 60).
        weights: 가중치. None이면 첫 번째 1.0, 이후 0.7.

    Returns:
        RRF 점수 내림차순, point.id 기준 중복 제거.
    """
    if not result_lists:
        return []
    if len(result_lists) == 1:
        return result_lists[0]

    if weights is None:
        weights = [1.0] + [0.7] * (len(result_lists) - 1)

    scores: dict[str, float] = {}
    points: dict[str, object] = {}

    for weight, result_list in zip(weights, result_lists):
        for rank, point in enumerate(result_list):
            pid = str(point.id)
            rrf_score = weight * (1.0 / (k + rank + 1))
            scores[pid] = scores.get(pid, 0.0) + rrf_score
            if pid not in points:
                points[pid] = point

    sorted_ids = sorted(scores, key=lambda pid: scores[pid], reverse=True)
    return [points[pid] for pid in sorted_ids]
```

---

## 6. 벤치마크 실행

```bash
# 500개 전체 벤치마크 (Baseline vs Full 비교)
python3 codes/query/test_query_decomposition.py \
    --set all \
    --output results/p1a_step1_hybrid.json

# 빠른 검증 (Set A만, ~12분)
python3 codes/query/test_query_decomposition.py \
    --set A \
    --output results/p1a_step1_hybrid_setA.json
```

---

## 7. 성공 기준

| 기준 | 임계값 | 근거 |
|------|--------|------|
| 전체 P@3 | ≥ 65.8% (Baseline 이상) | 원본 항상 포함 → 이론적으로 회귀 불가 |
| Set A P@3 | ≥ 79.3% | 정규 질의 보호 |
| Set B P@3 | ≥ 50% (+4%p) | REWRITE + 원본 보존 효과 |
| Set C P@3 | ≥ 81.0% | Cross-domain 보호 |
| 회귀 건수 | 0건 | Baseline 대비 신규 회귀 없음 |
| Latency p95 | ≤ 130ms | 2배 검색(원본+변환) → 최대 2× |

---

## 8. 가중치 튜닝 전략

초기 결과가 기대 미달 시:

| 시나리오 | 조정 |
|---------|------|
| Set A 회귀 | ORIGINAL_WEIGHT_REWRITE 1.0 → 1.5 |
| Set B 개선 미달 | TRANSFORMED_WEIGHT_REWRITE 0.8 → 1.0 |
| DECOMPOSE 회귀 | ORIGINAL_WEIGHT_DECOMPOSE 1.2 → 1.5 |

그리드 서치 (필요시):
```python
ORIGINAL_WEIGHTS = [0.8, 1.0, 1.2, 1.5]
TRANSFORMED_WEIGHTS = [0.5, 0.6, 0.8, 1.0]
# 16 조합 × ~42분/조합 → 선택적 실행
```

---

## 9. 폴백 계획

하이브리드가 악화되는 경우 (확률 < 5%):
1. 가중치를 `[1.0]` (원본 단독)으로 복원 → Baseline과 동일
2. REWRITE만 하이브리드, DECOMPOSE는 원본 단독으로 전환

---

## 10. 절대 하지 말 것

- **변환 질의만 단독 검색** (원본 제외 금지) — 회귀의 근본 원인
- **k 값을 무작위 변경** — k=60은 원 논문에서 검증된 값. 변경 시 대규모 벤치마크 필요
- **가중치 합이 1이 되도록 정규화** — 불필요. RRF는 순위 기반이므로 절대 점수가 아닌 상대 순위가 중요

---

## 11. 실행 체크리스트

- [ ] `config.py` 가중치 상수 4개 확인
- [ ] `pipeline.py` search()에서 원본 항상 검색 확인
- [ ] `pipeline.py` _compute_weights() 로직 확인
- [ ] `merger.py` rrf_merge() weights 파라미터 확인
- [ ] 단위 테스트: SIMPLE/REWRITE/DECOMPOSE 각 1개 수동 실행
- [ ] 500개 벤치마크 실행 (~42분)
- [ ] 결과 분석: P@3 비교, 회귀 0건 확인

---

## 12. 참고 문헌

| 자료 | 출처 |
|------|------|
| RAG-Fusion (Raudaschl, 2023) | https://github.com/Raudaschl/rag-fusion |
| HyDE (Gao et al., ACL 2023) | https://arxiv.org/abs/2212.10496 |
| Query2Doc (Wang et al., EMNLP 2023) | https://aclanthology.org/2023.emnlp-main.585/ |
| RRF (Cormack et al., 2009) | University of Waterloo, SIGIR 2009 |
| Scaling RAG Fusion (2026.03) | https://arxiv.org/abs/2603.02153 |
