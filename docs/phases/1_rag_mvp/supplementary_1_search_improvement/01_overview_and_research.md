# Phase 1 RAG MVP 검색 성능 향상 — 개요 및 기법 연구

> 작성일: 2026-03-29
> 선행 문서: `1_rag_mvp_plan.md`, Phase 2 `7_phase2_comprehensive_evaluation.md`
> 목적: Phase 1 RAG MVP에 적용할 추가 성능 향상 기법을 연구하고, 우선순위를 결정한다

---

## 0. 배경 및 동기

### 현재 상태 (Phase 1 + Phase 2 부분 완료)

Phase 1에서 구축한 RAG 파이프라인의 핵심 구성:

| 구성 요소 | 현재 상태 | 비고 |
|-----------|----------|------|
| 임베딩 모델 | KURE-v1 (realestate_v2), BGE-M3 (ontology/legal) | 듀얼 모델 |
| 벡터 DB | Qdrant v1.17.0 (Dense + Sparse BM25) | 93,943 청크 / 6,343문서 (3/15 마지막 색인) |
| **데이터 소스** | **rag_v2/: 11,035문서** | **~4,692문서 미색인 (3/15 이후 추가)** |
| 데이터 파이프라인 | Cron 활성 (8분/3파일, 야간) | notes_rag_todo 30,335 → rag_v2 변환 중 |
| 검색 | Dense + Sparse → RRF 합산 + 조건부 CE 리랭킹 | Phase 2에서 도입 |
| 질의 분석 | 2단계 게이팅 (룰 기반 + Claude Sonnet LLM) | SIMPLE/REWRITE/DECOMPOSE |
| 답변 생성 | **미구현** | Phase 1 최대 gap |

#### 데이터 현황 상세 (2026-03-30 기준)

| 디렉토리 | 파일 수 | 크기 | 형식 | 상태 |
|----------|--------|------|------|------|
| `rag_v2/` | **11,035** | 155MB | v2 MD (YAML frontmatter) | 색인 소스, **4,692개 미색인** |
| `notes_rag_todo/` | 30,335 | 626MB | 원본 스크립트 | 변환 대기 (Cron 처리 중) |
| `notes_rag_done/` | 4,963 | 129MB | v1 MD | 처리 완료 아카이브 |
| `ontology_data/entries/` | 10 JSON | ~2,146 엔트리 | 온톨로지 | Phase 2 완료 |

> **즉시 조치 필요**: `realestate_v2` 컬렉션이 3/15 이후 재색인되지 않아 4,692개 신규 문서가 검색 불가 상태. 재색인 시 ~57,000 청크 추가 예상 (문서당 평균 12.2 청크 × 4,692 = ~57,242). 전체 컬렉션: 93,943 → **~151,185 청크**.

### 해결 대상 성능 gap

500개 질의 벤치마크 결과 (Setting C: Dense+Sparse RRF):

| 질의 세트 | P@3 | 문제점 |
|-----------|-----|--------|
| Set A (정규 질의) | 79% | 양호 |
| Set B (극단 구어체) | **60%** | Phase 2A CE bypass로 +14%p 개선, 여전히 최약 |
| Set C (크로스 도메인) | 82% | 양호 |
| Set D (구어체) | **55%** | 어휘 격차 |
| Set E (인터넷 슬랭) | **55%** | 슬랭 커버리지 부족 |
| **전체** | **68.0%** | **목표: 75%+** |

**핵심 문제 4가지:**
1. **구어체-전문용어 어휘 격차** — "집 살 때 세금" vs "취득세" (Overlap@5: 20%, 정규 80% vs 구어체 57% = 23%p 격차)
2. **LLM 답변 생성 레이어 부재** — 검색만 하고 답변을 생성하지 못함
3. **검색 파이프라인 최적화가 한계에 도달** — Phase 2 종합 평가에서 확인. 추가 개선은 답변 생성 레이어에서 발생해야 함
4. **realestate_v2 컬렉션 스테일** — rag_v2에 11,035문서가 있으나 6,343문서만 색인됨. 4,692개 미색인 문서를 포함하면 코퍼스 다양성과 구어체 커버리지가 대폭 증가할 수 있음 (YouTube 전문가 스크립트에 구어체 표현이 자연스럽게 포함)

---

## 1. 연구 기법 총괄

12개 기법을 5개 Sprint로 구성한다. Phase 2에서 이미 연구/구현된 기법과 **중복되지 않는** 것만 선별했다.

### 1-1. 기법 우선순위 매트릭스

| 순위 | 기법 | Sprint | 기대 효과 | 난이도 | 재색인? | Phase 2 중복? |
|------|------|--------|----------|--------|---------|--------------|
| 1 | Parent Document Retrieval | 1 | Generation 품질 | LOW | No | No |
| 2 | Query-Time HyDE | 1 | P@3 +5-8% (구어체) | MED | No | No |
| 3 | RAG-Fusion (Multi-Query) | 1 | Recall +5-10% | LOW | No | 확장 |
| 4 | Dynamic Alpha Tuning | 1 | P@3 +3-5% | LOW | No | **이미 부분 구현** (4개 버킷 α) |
| 5 | CRAG (Post-Retrieval 검증) | 2 | 이미 적용, net +0%p (세트별 상쇄) | MED | No | **이미 구현** (compensator.py) |
| 6 | Listwise LLM Reranking | 2 | Set B/E +3-5% | MED | No | No |
| 7 | Adaptive RAG (LangGraph) | 3 | 핵심 제품 기능 활성화 | HIGH | No | No |
| **0** | **realestate_v2 재색인 (4,692 미색인 문서)** | **0 (선행)** | **코퍼스 +74% 확대** | **LOW** | **Yes** | **No** |
| 8 | Fact Group 청크 | 4 | Overlap@5 →35%+ | MED | 부분 | No |
| 9 | Late Chunking | 4 | 정밀도 +5-10% | MED | Yes | No |
| 10 | RAGAS 평가 | 5 | 측정 체계 강화 | LOW | No | No |
| 11 | RAPTOR (트리 요약) | 후속 | 주제 질의 +10-15% | HIGH | Yes | No |
| 12 | GraphRAG | 후속 | Multi-hop 개선 | V.HIGH | Yes | No |

> **참고**: 슬랭 질의 시점 확장(slang query-time expansion)은 이미 `_expand_slang_query`로 구현 완료.

---

## 2. 기법별 상세 연구

### 2-1. Parent Document Retrieval (부모 문서 검색)

#### 무엇인가?

> **일상 비유**: 도서관에서 책을 찾을 때, 색인 카드(atomic_fact)로 정확한 위치를 찾고, 실제로는 그 **책의 해당 챕터 전체**(parent document)를 읽는 것과 같다. 색인 카드만 보면 맥락을 놓치기 때문이다.

검색은 작은 청크(atomic_fact, ~50토큰)로 정밀하게 하되, LLM에 전달할 때는 해당 청크가 속한 **원본 문서의 요약 + 전체 사실 목록**을 함께 전달하는 기법이다.

#### 왜 필요한가?

현재 시스템에서 검색된 atomic_fact 예시:

```
"조정대상지역 2주택 취득시 8% 중과"
```

이것만으로는 LLM이 "어떤 상황에서", "누구에게", "어떤 예외가 있는지" 등의 맥락을 알 수 없다. Parent Document를 함께 전달하면:

```
[문서 요약] 다주택자의 취득세 중과세율에 관한 내용. 1세대 2주택부터
4주택 이상까지 조정대상지역 여부에 따른 세율 차이를 설명한다.

[사실 1] 조정대상지역 2주택 취득시 8% 중과
[사실 2] 조정대상지역 3주택 이상 취득시 12% 중과
[사실 3] 비조정대상지역은 기본세율(1~3%) 적용
[사실 4] 일시적 2주택은 3년 내 기존주택 처분 시 중과 제외
...
```

#### 학술 근거

- **LangChain Parent Document Retriever** (2024) — https://python.langchain.com/docs/how_to/parent_document_retriever/
- **Multi-Vector Retriever** — 같은 문서를 여러 표현(요약, 사실, 질문)으로 색인하고 검색은 세분화, 반환은 통합

#### 현재 시스템과의 관계

`codes/embedding/chunker.py`가 이미 문서당 3종 청크(summary, atomic_fact, hyde)를 생성하며, 모든 청크의 payload에 `doc_id`가 저장되어 있다. 따라서 **재색인 없이** 검색 후 `doc_id`로 Qdrant를 한 번 더 조회하면 된다.

---

### 2-2. Query-Time HyDE (Hypothetical Document Embeddings)

#### 무엇인가?

> **일상 비유**: 시험 문제를 풀기 전에 "이 문제의 정답은 아마 이런 내용일 거야"라고 **가짜 정답을 먼저 써보고**, 그 가짜 정답과 비슷한 내용의 교과서 페이지를 찾는 전략이다.

사용자 질의를 직접 임베딩하는 대신, LLM에게 "이 질문에 대한 가상의 답변 문서"를 생성시키고, 그 가상 문서를 임베딩하여 검색하는 기법이다.

#### 기존 REWRITE와의 차이

| | REWRITE (현재) | Query-Time HyDE (신규) |
|---|---|---|
| **입력** | "집 살 때 세금 얼마야" | "집 살 때 세금 얼마야" |
| **LLM 출력** | "부동산 취득세 납부 의무" (질의 형태) | "부동산을 매입할 때 취득세가 부과되며, 주택의 경우 취득가액에 따라 1~3%의 세율이 적용됩니다. 조정대상지역 다주택자는 8~12%까지 중과됩니다." (답변 문서 형태) |
| **임베딩 대상** | 정규화된 질의 (짧음) | 가상 답변 문서 (풍부한 의미 신호) |

가상 답변은 정확할 필요가 없다. 핵심은 "취득세", "세율", "조정대상지역" 같은 **전문 용어를 임베딩에 포함시키는 것**이다.

#### 학술 근거

- Gao et al., "Precise Zero-Shot Dense Retrieval without Relevance Labels" (ACL 2023)
- HyDE는 한국어, 일본어에서 mContriever 대비 우수 성능 입증
- https://zilliz.com/learn/improve-rag-and-information-retrieval-with-hyde-hypothetical-document-embeddings

> **핵심 개념 — 임베딩 공간(Embedding Space)이란?**
>
> 임베딩 모델은 텍스트를 고차원 벡터(예: 1024차원의 숫자 배열)로 변환한다. 이 벡터들이 존재하는 공간을 "임베딩 공간"이라 한다.
>
> 의미가 비슷한 텍스트는 이 공간에서 **가까이** 위치한다. "집 살 때 세금"이라는 구어체는 "취득세 세율"이라는 전문용어와 의미는 같지만, 단어가 완전히 달라서 임베딩 공간에서 **멀리** 떨어질 수 있다.
>
> HyDE는 LLM이 생성한 가상 답변에 "취득세", "세율" 같은 전문용어가 포함되므로, 이 가상 답변의 임베딩은 실제 문서 임베딩과 **가까워진다**.

---

### 2-3. RAG-Fusion (Multi-Query 생성)

#### 무엇인가?

> **일상 비유**: 도서관에서 한 가지 검색어로만 찾지 않고, 같은 주제를 **여러 표현**으로 검색하여 결과를 합치는 것이다. "집 매매 세금", "부동산 취득세", "아파트 구입 비용" 세 가지로 검색하면 하나로 검색할 때보다 더 많은 관련 문서를 찾을 수 있다.

하나의 사용자 질의에서 LLM을 사용하여 3-5개의 변형 질의를 생성하고, 각각 독립적으로 검색한 후 **RRF(Reciprocal Rank Fusion)**로 결과를 합산하는 기법이다.

#### 현재 시스템과의 관계

현재 `pipeline.py`의 REWRITE 경로는 변환 질의를 **1개만** 생성한다. RAG-Fusion은 이를 3-5개로 확장하는 것이므로, 프롬프트 수정 + 기존 RRF 합산 로직 재사용만으로 구현 가능하다.

#### 학술 근거

- Rackauckas, "RAG-Fusion: A New Take on Retrieval-Augmented Generation" (arXiv:2402.03367, 2024)
- 다중 질의의 RRF 합산이 단일 질의 대비 recall 5-10% 향상

> **핵심 개념 — RRF (Reciprocal Rank Fusion)란?**
>
> 여러 검색 결과 리스트를 하나로 합치는 방법이다. 각 문서가 각 리스트에서 몇 번째인지(순위)를 기준으로 점수를 계산한다:
>
> ```
> RRF_score(문서d) = Σ 1/(k + rank_i(d))
> ```
>
> 여기서 `k`는 상수(보통 60), `rank_i(d)`는 i번째 검색 리스트에서 문서 d의 순위다.
>
> **비유**: 3명의 심사위원이 각각 영화를 순위 매긴 후, "1등에 10점, 2등에 5점, 3등에 3.3점..." 식으로 점수를 합산하여 최종 순위를 정하는 것과 같다. 여러 심사위원이 높이 평가한 영화일수록 최종 점수가 높다.

---

### 2-4. Dynamic Alpha Tuning (동적 α 가중치)

> **현재 상태**: Query-type별 4개 버킷 α가 Phase 2A에서 이미 구현 완료 (`config.py`: SIMPLE_FORMAL=0.7, SIMPLE_MIXED=0.5, REWRITE=0.4, COLLOQUIAL_OVERRIDE=0.3). 아래는 이를 연속적 회귀 모델로 발전시키는 방안.

#### 무엇인가?

현재 시스템에서 Cross-Encoder(CE) 리랭킹 시 최종 점수는 다음과 같이 계산된다:

```
final_score = α × rrf_rank_score + (1-α) × ce_score
```

α가 크면 원래 검색 순서(RRF)를 더 신뢰하고, α가 작으면 CE 점수를 더 신뢰한다.

현재는 질의 유형별로 4개 고정값을 사용:

```python
# config.py
ALPHA_BY_QUERY_TYPE = {
    "SIMPLE_FORMAL":  0.7,   # 정규 용어 → RRF 신뢰
    "SIMPLE_MIXED":   0.5,   # 기본값
    "REWRITE":        0.4,   # 구어체 변환
    "DECOMPOSE":      0.5,   # 복합 분해
}
```

Dynamic Alpha Tuning은 이 4개 버킷 대신, 질의의 여러 특성(구어체 점수, 매칭 용어 수, 질의 길이, 도메인 수)을 입력으로 받아 **연속적인 최적 α를 예측**하는 회귀 모델을 사용한다.

> **일상 비유**: 요리할 때 "고기 요리엔 소금 많이, 생선엔 적게"라는 규칙(고정 버킷) 대신, 재료의 무게, 수분 함량, 조리 시간을 고려해 **정확한 소금 양을 계산하는 레시피**(회귀 모델)를 만드는 것이다.

#### 학술 근거

- Gao et al., "DAT: Dynamic Alpha Tuning for Hybrid Retrieval in RAG" (arXiv:2503.23013, March 2025)
- MRR 0.410 → 0.486 개선 (Hybrid Search에서)

---

### 2-5. CRAG (Corrective Retrieval Augmented Generation)

> **현재 상태**: CRAG는 Phase 2A/B에서 이미 구현 완료 (`codes/query/compensator.py`). Rule-based fast path + LLM 평가 2단계 게이팅으로 CORRECT/AMBIGUOUS/INCORRECT 3단계 판정 적용 중. 단, 단일 파이프라인에서 세트별 효과가 상쇄되어 전체 P@3 기여는 +0%p. 아래는 추가 개선 방향.

#### 무엇인가?

> **일상 비유**: 시험지에 답을 적기 전에, "내가 찾은 참고 자료가 정말 이 문제에 맞는 건지" **한 번 더 확인**하는 단계이다. 만약 엉뚱한 참고 자료를 찾았다면, 다른 자료를 다시 찾거나, 찾은 자료에서 관련 부분만 발췌한다.

검색 결과를 LLM에 전달하기 **전에**, 결과의 관련성을 평가하는 단계를 추가하는 기법이다:

```
검색 결과 → [평가기(Evaluator)] → {정확 / 부정확 / 모호}
  ↓ 정확: 그대로 LLM에 전달
  ↓ 부정확: 다른 컬렉션에서 재검색 (Fallback)
  ↓ 모호: 관련 부분만 추출 (Knowledge Refinement)
```

#### 학술 근거

- Yan et al., "Corrective Retrieval Augmented Generation" (ICLR 2024, arXiv:2401.15884)
- 후속: ICML 2024 채택

> **핵심 개념 — Hallucination(환각)이란?**
>
> LLM이 검색 결과에 없는 내용을 마치 사실처럼 생성하는 현상이다. 예를 들어, 검색 결과에 "취득세율 1~3%"만 있는데 LLM이 "4주택 이상은 15%"라고 지어내는 것이다.
>
> CRAG는 **부정확한 검색 결과 자체를 걸러내어**, LLM이 엉뚱한 정보를 기반으로 답변하는 것을 방지한다.

---

### 2-6. Listwise LLM Reranking

#### 무엇인가?

기존 Cross-Encoder(CE)는 각 문서를 **개별적으로**(pointwise) 점수를 매긴다. Listwise Reranking은 상위 5개 후보를 LLM에 **한꺼번에** 보여주고, "이 중에서 질문에 가장 관련 있는 순서대로 정렬하라"고 지시하는 기법이다.

> **일상 비유**: 면접관이 지원자를 한 명씩 만나서 점수를 매기는 것(pointwise CE)과, 5명을 한 방에 모아놓고 "이 중 누가 가장 적합한지 비교해서 순위를 매기라"고 하는 것(listwise)의 차이이다. 후자가 상대 비교가 가능하므로 더 정확할 수 있다.

#### 왜 필요한가? — CE 양극화 문제

Phase 2 테스트에서 발견된 문제: CE 모델(bge-reranker-v2-m3-ko)의 점수가 대부분 0 또는 1 근처로 몰린다(BCE loss 학습 특성). 극단 구어체에서는 정답의 CE 점수가 0.01, 오답이 0.03으로 나와 **오답이 더 높게 평가**되는 역전 현상이 발생한다.

현재 해결책은 구어체 질의에서 CE를 **스킵**하는 것(`_should_skip_rerank()`). 하지만 이는 리랭킹의 이점을 완전히 포기하는 것이다. Listwise LLM Reranking은 **스킵 대신 대체**하는 접근이다.

#### 학술 근거

- ZeroEntropy, "The Ultimate Guide to Choosing the Best Reranking Model in 2025" — https://www.zeroentropy.dev/articles/ultimate-guide-to-choosing-the-best-reranking-model-in-2025
- Fin.ai, "Using LLMs as Reranker for RAG: A Practical Guide" (2024) — https://fin.ai/research/using-llms-as-a-reranker-for-rag-a-practical-guide/

---

### 2-7. Adaptive RAG (LangGraph)

#### 무엇인가?

> **일상 비유**: 복잡한 질문을 받았을 때, 단순히 "검색 → 답변"이 아니라 **스스로 판단하는 비서**처럼 행동하는 것이다:
> 1. "이 질문은 간단한가, 복잡한가?" (복잡도 판단)
> 2. "찾은 자료가 충분한가?" (문서 평가)
> 3. "내 답변이 자료에 근거하는가?" (팩트 체크)
> 4. "답변이 불충분하면 다시 찾아보자" (재시도)

질의 복잡도에 따라 검색 전략을 **적응적으로** 선택하고, 검색 → 생성 → 검증 → 재시도의 루프를 자동으로 수행하는 상태 머신 기반 RAG 패턴이다.

```
    ┌────────────────────────────────────────────────┐
    │                                                │
    ▼                                                │
[QueryAnalyzer] → [Retrieve] → [Grade Docs] → [Generate] → [Hallucination Check]
                       ▲                │                          │
                       │           (불합격)                    (불합격)
                       │                ▼                          │
                       └──── [Rewrite Query] ◄─────────────────────┘
```

#### 학술 근거

- Jeong et al., "Adaptive-RAG: Learning to Adapt Retrieval-Augmented LLMs through Question Complexity" (NAACL 2024)
- LangGraph Adaptive RAG Tutorial — https://langchain-ai.github.io/langgraph/tutorials/rag/langgraph_adaptive_rag/

> **핵심 개념 — 상태 머신(State Machine)이란?**
>
> 프로그램이 여러 "상태" 사이를 **조건에 따라 전환**하며 동작하는 설계 패턴이다.
>
> 예: 자판기의 상태 = {대기중, 동전투입됨, 음료선택됨, 배출중}
> 각 상태에서 특정 이벤트(동전 투입, 버튼 누름)가 발생하면 다음 상태로 전환된다.
>
> Adaptive RAG에서는 "검색 완료 → 문서 평가 → 합격이면 생성, 불합격이면 재검색"처럼 조건에 따라 다음 단계가 달라진다. LangGraph는 이런 상태 머신을 Python 그래프로 쉽게 구현할 수 있는 프레임워크이다.

---

### 2-8. Fact Group 청크

#### 무엇인가?

현재 청크 분포: summary 6.8%, atomic_fact **67.7%**, hyde 25.6%.

atomic_fact는 "조정대상지역 2주택 취득시 8% 중과" 같은 **단일 사실** (~50토큰)이다. 이들은 검색 precision은 높지만, 한 개의 사실만으로는 충분한 맥락을 제공하지 못한다.

Fact Group은 **같은 문서 내 관련 있는 3-5개 atomic_fact를 묶어** ~150-300토큰의 중간 크기 청크를 만드는 것이다.

> **일상 비유**: 사전에서 단어 하나(atomic_fact)만 찾으면 정의는 알 수 있지만, 그 단어가 포함된 **문단**(fact_group)을 읽어야 "이 단어가 어떤 맥락에서 쓰이는지"를 이해할 수 있다.

#### 학술 근거

- Chen et al., "Dense X Retrieval: What Retrieval Granularity Should We Use?" (EMNLP 2024)
- 핵심 결론: proposition(atomic fact) 수준이 검색 precision에 최적이지만, 그것만으로는 recall이 부족 → 여러 granularity를 혼합하는 것이 최선

---

### 2-9. Late Chunking

#### 무엇인가?

기존 방식: 문서를 먼저 청크로 나누고(chunking), 각 청크를 독립적으로 임베딩
Late Chunking: 문서 전체를 트랜스포머에 통과시켜 **토큰별 맥락화된 임베딩**을 얻은 후, 청크 경계에서 잘라내고 평균 풀링

> **일상 비유**:
> - 기존 방식: 책의 각 페이지를 낱장으로 뜯어서 하나씩 요약 → 각 요약은 전후 페이지 내용을 모름
> - Late Chunking: 책 전체를 한 번 읽고 이해한 후, 각 페이지의 핵심을 정리 → 각 정리에 전후 맥락이 반영됨

핵심: "이 경우", "해당 세율은", "위 조건에 따라" 같은 **대명사/지시어**가 문서 맥락 없이 임베딩되면 의미를 잃는 문제를 해결한다.

#### 학술 근거

- Guenther & Moeller, "Late Chunking: Contextual Chunk Embeddings Using Long-Context Embedding Models" (Jina AI, arXiv:2409.04701, September 2024)
- Anthropic의 Contextual Retrieval과 유사 효과이나 **LLM 비용 없음** (트랜스포머 1회 추론만 필요)

> **핵심 개념 — 풀링(Pooling)이란?**
>
> 여러 벡터를 하나의 벡터로 압축하는 연산이다.
> - **평균 풀링(Mean Pooling)**: 여러 벡터의 각 차원을 평균 → 하나의 대표 벡터
> - 예: [1, 3, 5]와 [2, 4, 6]의 평균 풀링 → [1.5, 3.5, 5.5]
>
> Late Chunking에서는 청크 내 모든 토큰의 벡터를 평균 풀링하여 청크 임베딩을 만든다. 각 토큰 벡터가 이미 문서 전체 맥락을 반영하고 있으므로, 풀링 결과도 맥락이 보존된다.

---

### 2-10. RAGAS 평가 프레임워크

#### 무엇인가?

RAG 시스템의 품질을 자동으로 측정하는 프레임워크이다. 현재 시스템은 P@3 (검색 상위 3개 중 정답 비율)만 측정하지만, RAGAS는 **4가지 관점**에서 평가한다:

| 메트릭 | 측정 대상 | 질문 |
|--------|----------|------|
| **Faithfulness** | 생성 답변 | "답변이 검색 결과에 근거하는가?" (환각 감지) |
| **Answer Relevancy** | 생성 답변 | "답변이 질문에 적합한가?" (동문서답 감지) |
| **Context Precision** | 검색 결과 | "관련 청크가 상위에 있는가?" (순위 품질) |
| **Context Recall** | 검색 결과 | "필요한 모든 사실이 검색되었는가?" (누락 감지) |

> **일상 비유**: 학생의 리포트를 채점할 때:
> - Faithfulness: "출처에 없는 내용을 지어내지 않았는가?"
> - Answer Relevancy: "질문에 맞는 답을 했는가?"
> - Context Precision: "좋은 참고 자료를 찾았는가?"
> - Context Recall: "필요한 참고 자료를 빠짐없이 찾았는가?"

#### 학술 근거

- Es et al., "RAGAS: Automated Evaluation of Retrieval Augmented Generation" (EACL 2024, arXiv:2309.15217)
- https://docs.ragas.io/

---

### 2-11. RAPTOR (후속 과제)

#### 무엇인가?

문서 청크들을 임베딩 유사도로 **클러스터링**하고, 각 클러스터의 요약을 LLM으로 생성하여 상위 레벨 청크로 추가한다. 이 과정을 재귀적으로 반복하여 **트리 구조**를 만든다.

```
[Level 2: 주제 요약]    "다주택자 세금 전반 요약"
        ↑ (클러스터링 + LLM 요약)
[Level 1: 소주제 요약]  "취득세 중과" / "양도세 중과" / "종부세 합산"
        ↑ (클러스터링 + LLM 요약)
[Level 0: atomic_fact]  "2주택 8%" / "3주택 12%" / "비조정 기본세율" / ...
```

검색 시 모든 레벨을 동시에 검색하여, 구체적 질문에는 Level 0, 넓은 질문에는 Level 2가 매칭된다.

#### 학술 근거

- Sarthi et al., "RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval" (ICLR 2024, arXiv:2401.18059)

---

### 2-12. GraphRAG (후속 과제)

#### 무엇인가?

문서에서 **엔티티(개체)**와 **관계**를 추출하여 지식 그래프를 구축하고, 검색 시 그래프 탐색을 통해 관련 정보를 찾는 기법이다.

```
[취득세] ──관련세목──→ [양도소득세]
   │                      │
   │──적용대상──→ [다주택자]──→ [종합부동산세]
   │
   │──감면조건──→ [1세대1주택]
```

"재건축 아파트 팔 때 양도세 얼마"처럼 **여러 도메인을 넘나드는 질의**(multi-hop)에 강하다.

#### 학술 근거

- Microsoft GraphRAG (2024, open-source) — https://microsoft.github.io/graphrag/
- Peng et al., "Graph Retrieval-Augmented Generation: A Survey" (ACM TOIS 2025, arXiv:2408.08921)

---

## 3. 전체 참고 문헌 목록

| # | 논문/자료 | 기법 | 게재 |
|---|----------|------|------|
| 1 | Gao et al., "Precise Zero-Shot Dense Retrieval without Relevance Labels" | HyDE | ACL 2023 |
| 2 | Rackauckas, "RAG-Fusion: A New Take on RAG" | Multi-Query RRF | arXiv:2402.03367, 2024 |
| 3 | Gao et al., "DAT: Dynamic Alpha Tuning for Hybrid Retrieval" | Dynamic α | arXiv:2503.23013, 2025 |
| 4 | Yan et al., "Corrective RAG" | CRAG | ICLR 2024, arXiv:2401.15884 |
| 5 | Jeong et al., "Adaptive-RAG" | 복잡도 라우팅 | NAACL 2024 |
| 6 | Sarthi et al., "RAPTOR" | 재귀적 트리 검색 | ICLR 2024, arXiv:2401.18059 |
| 7 | Guenther & Moeller, "Late Chunking" | 맥락 보존 청킹 | arXiv:2409.04701, 2024 |
| 8 | Es et al., "RAGAS" | RAG 평가 | EACL 2024, arXiv:2309.15217 |
| 9 | Chen et al., "Dense X Retrieval" | Proposition Chunking | EMNLP 2024 |
| 10 | Anthropic, "Introducing Contextual Retrieval" | 맥락 prefix | Blog, 2024 |
| 11 | Microsoft, "GraphRAG" | 지식 그래프 RAG | Open Source, 2024 |
| 12 | ZeroEntropy, "Choosing the Best Reranking Model" | Listwise Reranking | Blog, 2025 |
| 13 | Fin.ai, "Using LLMs as Reranker" | LLM 리랭킹 | Blog, 2024 |
| 14 | Kim et al., "AutoRAG" | 한국어 RAG 벤치마크 | arXiv:2410.20878, 2024 |
| 15 | Asai et al., "Self-RAG" | 자기 반성 RAG | NeurIPS 2023 |
| 16 | Peng et al., "Graph RAG Survey" | GraphRAG 서베이 | ACM TOIS 2025 |
| 17 | Google Research, "Speculative RAG" | 초안 검증 RAG | arXiv:2407.08223, 2024 |
| 18 | Khattab et al., "DSPy" | 자동 파이프라인 최적화 | ICLR 2024 |
