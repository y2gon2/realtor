# BGE-M3 Triple-Vector + Multi-Stage Retrieval — 전체 계획

> 작성일: 2026-03-27
> 선행 문서: `5_phase2_search_test_report.md`, `6_search_improvement_research.md` §2, `supplementary_result/05_contextual_retrieval_results.md`
> 목적: Dense 단일 벡터의 한계를 극복하기 위해 BGE-M3의 3종 벡터(Dense+Sparse+ColBERT)와 Multi-Stage Retrieval 파이프라인을 구축

---

## 0. 배경 및 동기

### 해결 대상 약점 (Contextual Retrieval 적용 후 기준)

| 약점 | 현상 예시 | 현재 수치 | 목표 |
|------|----------|----------|------|
| **W2**: 극단적 구어체 ↔ 전문용어 격차 | "나라에 돈" → 취득세 Top-5에 없음 | 추상 질의 Precision@3 80% | 87%+ |
| **W4**: Top-1 점수 미흡 | Dense 단일 벡터 의존 | Avg Top-1 0.619 (ontology) | 0.72+ |
| **W5**: BM25 키워드 매칭 한계 | "몇 프로까지 빌려주는" → LTV 미매칭 | 6/12 법률 질의 RRF 0.5000 고착 | 스코어 개선 |

### 왜 Contextual Retrieval만으로 부족한가?

Contextual Retrieval(P0-a)은 각 청크 앞에 맥락 설명을 붙여 **의미 공간(semantic space)에서의 거리를 좁히는** 접근이었다. 이를 통해 Precision@3이 80%→90%로 향상되었다. 그러나 근본적인 한계가 있다:

1. **Dense 벡터는 문장 전체를 하나의 점으로 압축**한다. "집 살 때 세금"이라는 5단어를 1024차원 벡터 1개로 표현하면, 개별 단어("집", "세금")와 전문용어("주택", "취득세") 간의 세밀한 매칭이 불가능하다.

2. **BM25(키워드 검색)는 정확히 같은 단어만 매칭**한다. "빌려주는"이라고 검색하면 "대출"이나 "LTV"와는 매칭되지 않는다. 동의어 확장(synonym expansion)이 없다.

→ 이 두 한계를 동시에 해결하려면 **여러 종류의 벡터를 함께 사용**해야 한다. 이것이 BGE-M3 Triple-Vector의 핵심 아이디어다.

---

## 1. 핵심 개념 설명

### 1-1. 임베딩(Embedding)이란?

> **비유**: 모든 문장을 1024차원 공간의 한 점으로 변환하는 것. 의미가 비슷한 문장은 가까운 점에, 다른 문장은 먼 점에 위치한다.

텍스트를 숫자 벡터(리스트)로 변환하는 과정을 **임베딩**이라고 한다. 예를 들어 "취득세"라는 단어는 `[0.12, -0.45, 0.78, ..., 0.33]` 같은 1024개의 숫자로 표현된다.

```
"취득세"  →  [0.12, -0.45, 0.78, ..., 0.33]   (1024개 숫자)
"집 살 때 세금"  →  [0.10, -0.41, 0.72, ..., 0.29]   (비슷한 숫자들)
"오늘 날씨"  →  [-0.55, 0.82, -0.11, ..., -0.67]   (전혀 다른 숫자들)
```

두 벡터가 얼마나 비슷한지를 **코사인 유사도(cosine similarity)**로 측정한다. 값은 -1(완전 반대)~1(완전 동일) 사이다.

### 1-2. Dense 벡터 vs Sparse 벡터

현재 시스템에는 두 종류의 벡터가 있다:

#### Dense 벡터 (밀집 벡터)

- **모든 차원에 값이 있다** (1024개 숫자 전부 0이 아닌 값)
- 문장의 **전체 의미**를 포착한다
- 비유: 책 한 권의 내용을 한 줄 요약문으로 압축. 전체 맥락은 잡지만 세부 단어 매칭은 약하다

```python
# Dense 벡터 예시 (실제로는 1024차원)
dense = [0.12, -0.45, 0.78, 0.03, -0.21, ...]  # 모든 값이 채워져 있음
```

#### Sparse 벡터 (희소 벡터)

- **대부분의 차원이 0**이고, 특정 단어에 해당하는 차원만 값이 있다
- 문장에 **어떤 단어가 얼마나 중요한지**를 기록한다
- 비유: 도서관의 색인 카드. "취득세"라는 카드에만 표시가 되어 있고, 나머지 수만 장의 카드는 비어 있다

```python
# Sparse 벡터 예시 (수십만 차원 중 몇 개만 값 있음)
sparse = {
    4521: 2.3,    # "취득세" → 중요도 2.3
    8902: 1.1,    # "세율" → 중요도 1.1
    12045: 0.8,   # "다주택" → 중요도 0.8
    # ... 나머지 수십만 차원은 모두 0
}
```

#### 왜 둘 다 필요한가?

| 질의 | Dense가 잘 잡는 것 | Sparse가 잘 잡는 것 |
|------|-------------------|-------------------|
| "집 살 때 세금 얼마야" | "부동산 매수 시 발생하는 비용" (의미적 유사) | "세금", "얼마" (키워드 매칭) |
| "DSR 40% 넘으면?" | "대출 상환 능력 관련 규제" (의미적 유사) | "DSR", "40%" (정확한 용어) |

→ Dense는 의미를 잡고, Sparse는 키워드를 잡는다. **둘을 합치면(하이브리드 검색) 더 정확해진다.**

### 1-3. BGE-M3 모델이란?

**BGE-M3**(BAAI General Embedding, Multi-Functionality, Multi-Linguality, Multi-Granularity)는 중국 BAAI 연구소가 2024년에 발표한 임베딩 모델이다.

**핵심 특징**: 하나의 모델에서 **3종류의 벡터를 동시에 생성**할 수 있다.

```
입력: "다주택자 취득세 중과세율"
         ↓
    [BGE-M3 모델] (XLM-RoBERTa-large 기반)
         ↓
    ┌─────────────────────────────────────────────┐
    │ (1) Dense 벡터:  [0.12, -0.45, ..., 0.33]  │  ← 문장 전체의 의미
    │     shape: (1024,)                           │
    │                                              │
    │ (2) Sparse 벡터: {4521: 2.3, 8902: 1.1, ...}│  ← 각 단어의 중요도
    │     학습된 어휘 가중치 (SPLADE 방식)          │
    │                                              │
    │ (3) ColBERT 벡터: [[0.1, ...], [0.2, ...]]  │  ← 각 토큰별 벡터
    │     shape: (토큰 수, 1024)                    │
    └─────────────────────────────────────────────┘
```

#### 3종 벡터 상세 설명

| 벡터 종류 | 생성 원리 | 비유 | 역할 |
|----------|----------|------|------|
| **Dense** (1024D) | `[CLS]` 토큰의 hidden state를 정규화 | 책 한 권의 한 줄 요약 | 전체 의미 매칭 (Stage 1a) |
| **Sparse** (어휘 가중치) | 각 토큰마다 `ReLU(W × h)` 적용하여 중요도 계산 | 도서관 색인 카드 + **동의어 확장** | 키워드 매칭 (Stage 1b) |
| **ColBERT** (토큰별 벡터) | 각 토큰마다 별도 벡터 생성 `norm(W × h)` | 두 문장의 단어를 하나하나 짝지어 비교 | 정밀 재정렬 (Stage 3) |

#### BGE-M3 Sparse의 핵심: 동의어 확장

기존 BM25(Kiwi 형태소 분석 기반)는 **정확히 같은 단어**만 매칭한다. "집"으로 검색하면 "주택"은 매칭되지 않는다.

BGE-M3의 Sparse는 **학습된 어휘 가중치**를 사용한다. 모델이 대규모 텍스트로 훈련되면서 "집"이라는 단어가 나오면 "주택", "부동산", "아파트" 등 관련 단어도 함께 활성화하도록 학습된다.

```
BM25 (Kiwi 기반):
  "집 살 때 세금" → 활성화: {집, 살, 때, 세금}
  → "취득세"라는 단어가 없으므로 매칭 실패

BGE-M3 Sparse (학습 기반):
  "집 살 때 세금" → 활성화: {집, 주택, 부동산, 매수, 살, 때, 세금, 취득세, 납부, ...}
  → "취득세"도 활성화되어 매칭 성공!
```

이것이 현재 시스템의 W2(구어체 ↔ 전문용어 격차) 문제를 해결할 핵심이다.

### 1-4. ColBERT Late Interaction이란?

> **비유**: 시험 채점 시, 답안지의 각 문장을 정답지의 각 문장과 **하나하나** 비교하여 가장 잘 맞는 쌍을 찾는 방식.

**ColBERT**(Contextualized Late Interaction over BERT)는 2020년 Stanford에서 제안한 검색 모델이다. 핵심 아이디어는:

1. **쿼리와 문서를 각각 토큰 단위로 임베딩**한다 (Late: 나중에 비교)
2. 쿼리의 각 토큰에 대해, 문서의 모든 토큰 중 **가장 유사한 것**을 찾는다 (MaxSim)
3. 이 최대 유사도들을 **합산**하여 최종 점수를 계산한다

```
쿼리: "집 살 때 세금"
       ↓ 토큰별 벡터 생성
       [v_집, v_살, v_때, v_세금]

문서: "1세대 2주택 취득세 중과세율 8% 적용"
       ↓ 토큰별 벡터 생성
       [v_1세대, v_2주택, v_취득세, v_중과세율, v_8%, v_적용]

MaxSim 계산:
  v_집   → max(sim(v_집, v_1세대), sim(v_집, v_2주택), ...) = sim(v_집, v_2주택) = 0.72
  v_살   → max(sim(v_살, v_1세대), sim(v_살, v_2주택), ...) = sim(v_살, v_적용) = 0.31
  v_때   → max(sim(v_때, v_1세대), ...) = 0.15
  v_세금 → max(sim(v_세금, v_취득세), ...) = sim(v_세금, v_취득세) = 0.89

최종 점수 = 0.72 + 0.31 + 0.15 + 0.89 = 2.07
```

**왜 ColBERT가 강력한가?**

- "집"과 "주택"은 Dense 벡터에서는 문장 전체에 묻혀 희석될 수 있지만, ColBERT에서는 **토큰 대 토큰으로 직접 비교**하므로 높은 유사도(0.72)를 정확히 포착한다.
- Cross-encoder(질의+문서를 하나로 붙여 BERT에 입력)보다 **180배 빠르다**: 문서 벡터를 미리 계산해둘 수 있기 때문이다.

### 1-5. Multi-Stage Retrieval (다단계 검색)

3종 벡터를 **한꺼번에** 사용하면 너무 느리다. 대신 **단계적으로** 사용한다:

```
┌──────────────────────────────────────────────────────────┐
│ Stage 1: Prefetch — 후보 대량 수집 (병렬 실행, 빠르게)    │
│                                                          │
│  ┌─────────────────┐    ┌─────────────────┐             │
│  │  Dense 검색      │    │  Sparse 검색     │             │
│  │  (HNSW 인덱스)   │    │  (역색인)        │             │
│  │  → top-100 후보  │    │  → top-100 후보  │             │
│  └────────┬────────┘    └────────┬────────┘             │
│           │                      │                       │
│           └──────────┬───────────┘                       │
│                      ↓                                   │
│ Stage 2: Fusion — 두 리스트 합산                          │
│  RRF(Reciprocal Rank Fusion) → top-50                   │
│                      ↓                                   │
│ Stage 3: Rerank — 정밀 재정렬 (느리지만 정확)             │
│  ColBERT MaxSim으로 top-50을 재정렬 → top-10 최종 반환   │
└──────────────────────────────────────────────────────────┘
```

**왜 단계적으로?**

- Stage 1은 **빠르지만 대략적**이다 (수만 개 중에서 100개를 빠르게 골라냄)
- Stage 3은 **느리지만 정확**하다 (ColBERT MaxSim은 토큰 하나하나 비교하므로)
- 전체에 ColBERT를 적용하면 너무 느리니, 먼저 후보를 줄인 다음에만 적용한다

### 1-6. RRF(Reciprocal Rank Fusion)란?

> **비유**: 두 명의 심사위원이 각각 100명의 가수를 순위 매겼다. 한 심사위원은 100점 만점, 다른 심사위원은 10점 만점으로 채점했다. 점수를 직접 더하면 불공평하다. RRF는 **점수가 아니라 순위**를 기준으로 합산한다.

수식:
```
RRF_score(문서 d) = Σ  1 / (k + rank_i(d))
                   i∈{리스트들}
```

여기서:
- `k`는 상수 (보통 60)
- `rank_i(d)`는 i번째 검색 리스트에서 문서 d의 순위

**예시**: 문서 A가 Dense에서 3위, Sparse에서 5위라면:
```
RRF(A) = 1/(60+3) + 1/(60+5) = 0.0159 + 0.0154 = 0.0313
```

**장점**: Dense와 Sparse의 점수 스케일이 달라도 (코사인 유사도 0~1 vs BM25 점수 0~∞) 순위 기반이므로 공평하게 합산된다.

### 1-7. HNSW 인덱스란?

> **비유**: 도서관에서 책을 찾을 때, 모든 선반을 하나하나 확인하는 것(brute force)이 아니라, "이 분야 책은 3층 A구역에 있다"는 안내 체계를 따라가는 것.

**HNSW**(Hierarchical Navigable Small World)는 벡터 검색을 빠르게 하는 인덱스 구조다:

- 벡터들을 **그래프 형태**로 연결한다
- 검색 시 그래프의 상위 레이어에서 시작해 점점 세밀한 레이어로 내려가며 가장 가까운 벡터를 찾는다
- 전체를 다 비교하는 것(O(N))에 비해 **로그 시간(O(log N))**으로 검색 가능

ColBERT 벡터에는 `hnsw_config(m=0)` 설정을 사용하는데, 이는 **HNSW 인덱스를 만들지 않겠다**는 의미다. ColBERT는 Stage 3(리랭킹)에서만 사용하므로, 이미 후보가 50개로 줄어든 상태에서 brute force로 비교해도 충분히 빠르다. HNSW를 안 만들면 **메모리를 크게 절약**할 수 있다.

---

## 2. KURE-v1 vs BGE-M3: 왜 모델을 바꿔야 하는가?

### 2-1. KURE-v1의 한계

현재 시스템은 **KURE-v1**(Korea University Retrieval Embedding)을 사용한다. KURE-v1은 BGE-M3를 한국어에 맞게 fine-tune한 모델이다.

| 항목 | BGE-M3 (원본) | KURE-v1 (fine-tuned) |
|------|-------------|---------------------|
| 기반 아키텍처 | XLM-RoBERTa-large | 동일 (BGE-M3에서 출발) |
| 학습 방법 | Multi-task (Dense+Sparse+ColBERT 공동 학습) | `sentence-transformers` + `CachedGISTEmbedLoss` |
| Dense 벡터 | O (1024D) | **O** (1024D, 한국어 최적화) |
| Sparse 벡터 | O (SPLADE 방식 학습됨) | **X** (학습 안 됨) |
| ColBERT 벡터 | O (토큰별 벡터 학습됨) | **X** (학습 안 됨) |
| 한국어 Dense 성능 | 좋음 (MTEB-ko 상위) | **최고** (MTEB-ko 1위) |

**핵심 문제**: KURE-v1은 Dense 임베딩만 학습시켰기 때문에, Sparse와 ColBERT head가 BGE-M3 원본 가중치와 **불일치(misaligned)** 상태다. 즉, KURE-v1에서 Sparse/ColBERT를 추출하면 **쓸모없는 벡터**가 나온다.

### 2-2. 듀얼 모델 전략

해결 방법: **두 모델을 동시에 사용한다.**

```
realestate_v2 컬렉션 (93,943 포인트)  ←  KURE-v1 (Dense + Kiwi BM25)
  → 한국어 Dense 성능 최고, 이미 색인 완료, 재인덱싱 불필요

domain_ontology_v2 컬렉션 (2,146 포인트)  ←  BGE-M3 (Dense + Sparse + ColBERT)
legal_docs_v2 컬렉션 (~976 포인트)       ←  BGE-M3 (Dense + Sparse + ColBERT)
  → 3종 벡터 활용, 소규모이므로 재인덱싱 부담 적음
```

BGE-M3의 Dense 성능이 KURE-v1보다 약간 낮을 수 있지만(~0.5-1%), **Sparse + ColBERT가 추가되면서 전체 파이프라인에서 충분히 보상**된다.

---

## 3. 외부 연구 조사 결과

### 3-1. BGE-M3 논문 (BAAI, 2024)

- **제목**: M3-Embedding: Multi-Linguality, Multi-Functionality, Multi-Granularity
- **출처**: https://arxiv.org/abs/2402.03216
- **핵심**: 100+ 언어 지원, 8192 토큰까지 입력 가능, 단일 모델에서 3종 벡터 동시 생성
- **학습 방법**: Self-knowledge distillation — `s_teacher = s_dense + s_sparse + s_colbert`로 3종 점수를 합산한 것을 교사 신호로 사용하여 각 head를 공동 학습
- **벤치마크**: MIRACL(다국어 검색)에서 기존 모델 대비 상위 성능, 한국어 포함

### 3-2. Qdrant Multi-Vector 지원

- **버전**: v1.10.0부터 `multivector_config` 지원 (현재 v1.17.0)
- **MaxSim**: Qdrant 내부에서 ColBERT의 MaxSim 연산을 네이티브로 수행
- **Nested Prefetch**: 단일 API 호출로 Dense→Sparse→ColBERT 다단계 검색 가능
- **참고**: https://qdrant.tech/documentation/concepts/vectors/#multivectors

### 3-3. 성능 기대치 (외부 벤치마크 종합)

| 구성 | nDCG@10 개선폭 (vs Dense-only) | 레이턴시 |
|------|-------------------------------|---------|
| Dense only (현재) | baseline | ~30ms |
| + Sparse (하이브리드) | **+8-12%** | ~80ms |
| + ColBERT 리랭킹 | **+10% 추가** | ~200ms |
| **전체 파이프라인** | **+25% 평균, 최대 +48%** | ~200ms |

### 3-4. FlagEmbedding 라이브러리

BGE-M3를 Python에서 사용하기 위한 공식 라이브러리:

```python
from FlagEmbedding import BGEM3FlagModel

model = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)
output = model.encode(
    sentences,
    return_dense=True,         # Dense 벡터 반환
    return_sparse=True,        # Sparse 어휘 가중치 반환
    return_colbert_vecs=True,  # ColBERT 토큰별 벡터 반환
    batch_size=12,
    max_length=8192,
)

# 결과:
# output['dense_vecs']       → numpy array, shape (N, 1024)
# output['lexical_weights']  → list of dicts, {token_id: weight}
# output['colbert_vecs']     → list of numpy arrays, shape (num_tokens, 1024)
```

### 3-5. 참고 문헌 목록

| # | 자료 | URL |
|---|------|-----|
| 1 | BGE-M3 논문 | https://arxiv.org/abs/2402.03216 |
| 2 | BGE-M3 HuggingFace 모델 | https://huggingface.co/BAAI/bge-m3 |
| 3 | FlagEmbedding GitHub | https://github.com/FlagOpen/FlagEmbedding |
| 4 | Qdrant Multi-Vector 문서 | https://qdrant.tech/documentation/concepts/vectors/#multivectors |
| 5 | Qdrant Late Interaction 가이드 | https://qdrant.tech/articles/late-interaction-models/ |
| 6 | Qdrant Hybrid Search 가이드 | https://qdrant.tech/articles/hybrid-search/ |
| 7 | Qdrant Hybrid Queries API | https://qdrant.tech/documentation/search/hybrid-queries/ |
| 8 | BGE-M3 + Qdrant 샘플 코드 | https://github.com/yuniko-software/bge-m3-qdrant-sample |
| 9 | KURE-v1 모델 | https://huggingface.co/nlpai-lab/KURE-v1 |
| 10 | KURE GitHub | https://github.com/nlpai-lab/KURE |
| 11 | ColBERT 원본 논문 | https://arxiv.org/abs/2004.12832 |
| 12 | Qdrant v1.10 릴리즈 (ColBERT+IDF 지원) | https://qdrant.tech/blog/qdrant-1.10.x/ |

---

## 4. 설계 결정 요약

### D1: 듀얼 모델 아키텍처
- `realestate_v2`: KURE-v1 유지 (93,943 포인트 재인덱싱 불필요)
- Phase 2 컬렉션: BGE-M3 전환 (3,122 포인트, 소규모)
- 새 모듈 `embedder_bgem3.py` 생성, 기존 `embedder.py` 미수정

### D2: Sparse 벡터 — BGE-M3 learned sparse 사용
- BGE-M3 sparse는 동의어 확장 가능 (SPLADE 방식)
- 현재 약점인 어휘 격차 해결의 핵심
- 벤치마크에서 BGE-M3 sparse vs Kiwi BM25 비교 포함

### D3: 컬렉션 버전닝
- `domain_ontology_v2`, `legal_docs_v2` 신규 생성
- 기존 v1 컬렉션 유지하여 A/B 비교 가능

### D4: 저장 최적화
- ColBERT: `hnsw_config(m=0)` (리랭킹 전용, 인덱스 미구축)
- ColBERT: INT8 스칼라 양자화 (4배 압축)
- 예상 총 저장: ~400MB (128GB 환경에서 충분)

---

## 5. 구현 단계 개요

| Step | 작업 | 산출물 | 문서 |
|------|------|--------|------|
| **1** | Docker 의존성 추가 | `docker-compose.yml` 수정 | 본 문서 §6 |
| **2** | BGE-M3 Embedder 구현 | `embedder_bgem3.py` | `02_embedder_bgem3_design.md` |
| **3** | Qdrant 스키마 + 인덱싱 | `index_phase2_v2.py` | `03_collection_schema_and_indexing.md` |
| **4** | Multi-Stage 검색 파이프라인 | `search_test_phase2_v2.py` | `04_multi_stage_search_pipeline.md` |
| **5** | 벤치마크 + Ablation | `benchmark_phase2_v2.py` | `05_benchmark_and_ablation.md` |
| **6** | 결과 분석 | 결과 문서 | `06_results_and_analysis.md` |

---

## 6. Step 1: Docker 의존성 추가

### 6-1. 현재 상태

`docker-compose.yml`의 embedding 서비스는 다음 패키지를 설치한다:
```bash
pip install --quiet "numpy<2.0" sentence-transformers qdrant-client tqdm pyyaml
```

### 6-2. 변경 내용

`FlagEmbedding`과 `kiwipiepy`를 추가한다:
```bash
pip install --quiet "numpy<2.0" sentence-transformers qdrant-client tqdm pyyaml kiwipiepy FlagEmbedding
```

- **FlagEmbedding**: BGE-M3 모델의 3종 벡터를 추출하기 위한 공식 라이브러리
- **kiwipiepy**: 한국어 형태소 분석기 (기존 sparse_bm25.py에서 사용, 명시적 추가)

### 6-3. 검증 방법

```bash
docker compose -f docker/docker-compose.yml up -d
docker exec rag-embedding python -c "from FlagEmbedding import BGEM3FlagModel; print('OK')"
```

---

## 7. 성공 기준

| 지표 | 현재 (v1, KURE-v1) | 목표 (v2, BGE-M3 Triple) |
|------|-------------------|-------------------------|
| Precision@3 (전체 45개) | 84% | **≥ 90%** |
| Precision@3 (추상 질의 27개) | 80% | **≥ 87%** |
| Avg Top-1 Ontology | 0.619 | **≥ 0.72** |
| Avg Top-1 Legal | 0.612 | **≥ 0.70** |
| Latency p95 | ~50ms | **< 200ms** |

---

## 8. 리스크 및 완화 방안

| 리스크 | 영향 | 완화 방안 |
|--------|------|----------|
| BGE-M3 ColBERT 출력이 GPU 메모리 초과 | 인덱싱 실패 | `batch_size=32`, `max_length=512`, `use_fp16=True` |
| ColBERT 저장 용량 폭증 (~1.5GB float32) | 디스크 부족 | INT8 양자화 → ~400MB로 압축 |
| BGE-M3 한국어 Dense가 KURE-v1보다 낮음 | Top-1 점수 하락 | Ablation 테스트로 확인; Sparse+ColBERT로 보상 |
| FlagEmbedding 패키지 충돌 | 설치 실패 | NGC PyTorch 컨테이너에 호환 패키지 이미 존재 |
| Qdrant MultiVector API 미지원 | 컬렉션 생성 실패 | Qdrant v1.17.0 > v1.10.0 (지원 시작 버전) |
| Upsert 시 ColBERT 페이로드로 타임아웃 | 인덱싱 중단 | 배치 크기 100→50, timeout 120s |
