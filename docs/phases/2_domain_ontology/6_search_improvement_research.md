# Phase 2 검색 성능 개선 연구: 외부 유사 사례 기반

> 작성일: 2026-03-26
> 선행 문서: `4_ontology_build_and_index_plan.md`, `5_phase2_search_test_report.md`
> 목적: Phase 2 검색 테스트에서 드러난 약점을 외부 연구·사례 기반으로 개선하는 전략 수립

---

## 0. 현재 약점 진단 (5_phase2_search_test_report.md 기준)

| # | 약점 | 현상 예시 | 영향 지표 |
|---|------|----------|----------|
| W1 | **Cross-domain 질의 실패** | "경매 낙찰 세금" → 경매 브랜치에만 편향, 세금 브랜치 결과 누락 | Precision@3에서 2/10 실패 |
| W2 | **추상적 구어체 질의** | "집 살 때 세금" → "취득세"가 4위, 일반 세금 용어가 상위 독점 | Top-1 score 0.611 |
| W3 | **table_fact 맥락 손실** | 행 단위 분리로 "이 표가 무엇에 대한 표인지" 정보 유실 | 수치 검색 정밀도 부족 |
| W4 | **전체 Top-1 점수 미흡** | Dense 단일 벡터 의존, 평균 0.5~0.6 수준 | 실서비스 신뢰도 부족 |

---

## 1. Contextual Retrieval — 맥락 prefix 주입 후 재임베딩

### 1-1. 개념 설명

**Contextual Retrieval**은 Anthropic이 2024년에 발표한 기법이다. 핵심 아이디어는 단순하다:

> 각 청크(chunk)를 임베딩하기 **전에**, LLM을 사용해 해당 청크가 **문서 전체에서 어떤 맥락에 위치하는지를 1~2문장으로 요약**한 prefix를 붙인다.

**비유**: 도서관에서 책 한 페이지만 복사해 놓으면 "이게 무슨 책의 몇 장인지" 알 수 없다. Contextual Retrieval은 복사한 페이지 상단에 "이 페이지는 《부동산 세법 해설》 제3장 '취득세' 중 '다주택자 중과세율'을 다루는 부분입니다"라고 메모를 붙이는 것과 같다.

**예시** — domain_ontology 엔트리 변환:

```
[변환 전 — 현재]
임베딩 텍스트: "취득세 | 다주택자 취득세 중과세율, 집 여러 채 살 때 취득세,
2주택 취득세 8퍼센트 | 1세대 2주택(조정대상지역) 취득 시 8% 중과..."

[변환 후 — Contextual Retrieval 적용]
임베딩 텍스트: "이 항목은 부동산을 매수(구매)할 때 발생하는 세금인 '취득세'에
관한 것으로, 일반인들이 '집 살 때 세금', '아파트 사면 세금 얼마'라고
표현하는 개념입니다. | 취득세 | 다주택자 취득세 중과세율, 집 여러 채 살 때
취득세... [이하 동일]"
```

**예시** — legal_docs 청크 변환:

```
[변환 전]
"1세대가 1주택을 보유하면서 보유기간 2년 이상인 경우 양도소득세를 비과세한다."

[변환 후]
"이 문단은 《2025 주택과 세금》 제4편 '양도소득세' 중 '1세대 1주택 비과세'
조건을 설명하는 부분입니다. 일반적으로 '내 집 팔 때 세금 안 내도 되나요?'라는
질문에 대한 답변 근거가 됩니다. | 1세대가 1주택을 보유하면서 보유기간 2년 이상인
경우 양도소득세를 비과세한다."
```

### 1-2. 기대 효과

| 조합 | 검색 실패 감소율 (Anthropic 벤치마크) |
|------|--------------------------------------|
| Contextual Embeddings 단독 | **-35%** |
| Contextual Embeddings + Contextual BM25 | **-49%** |
| Contextual Embeddings + BM25 + Reranking | **-67%** |

### 1-3. 구현 계획

| 단계 | 작업 | 사용 모델 | 비고 |
|------|------|----------|------|
| A | domain_ontology 2,146개 엔트리에 대해 맥락 prefix 생성 | **Claude 4.6 Sonnet** | 방대한 양, 정형화된 패턴 반복 작업 |
| B | legal_docs 976개 청크에 대해 맥락 prefix 생성 | **Claude 4.6 Sonnet** | 위와 동일 |
| C | prefix 품질 검수 (샘플 50개) | **Claude 4.6 Opus** | 맥락이 정확한지, 구어체 표현이 자연스러운지 검증 |
| D | 재임베딩 + Qdrant 재색인 | KURE-v1 (GPU) | 기존 index_phase2.py 재사용 |

**처리 규모**: 총 3,122개 포인트 × prefix 생성 1회 = Sonnet 배치 약 3,200 호출

### 1-4. 해결하는 약점

- **W2 (추상 질의)**: "집 살 때 세금" → prefix에 "집 살 때 세금"이 명시적으로 포함되므로 취득세가 top-1으로 상승
- **W4 (Top-1 점수)**: 전체적으로 질의-청크 간 의미 거리가 좁아져 점수 향상

### 1-5. 참고 자료

- Anthropic, "Contextual Retrieval" (2024) — https://www.anthropic.com/news/contextual-retrieval
- DataCamp Tutorial — https://www.datacamp.com/tutorial/contextual-retrieval-anthropic

---

## 2. BGE-M3 Triple-Vector + Multi-Stage Retrieval

### 2-1. 개념 설명

현재 시스템은 KURE-v1(BGE-M3 기반)의 **Dense 벡터 1종**만 사용한다. 그런데 BGE-M3는 실제로 **3종의 벡터를 동시에 생성**할 수 있다:

| 벡터 종류 | 작동 원리 | 비유 |
|----------|----------|------|
| **Dense** (1024차원) | 문장 전체의 의미를 하나의 고정 크기 벡터로 압축 | 책 한 권의 내용을 한 줄 요약문으로 압축하는 것. 전체 맥락은 잡지만 세부 단어 매칭은 약하다 |
| **Sparse** (어휘 가중치) | SPLADE 방식으로 각 단어의 중요도를 학습. BM25와 유사하지만 "동의어 확장"이 가능 | 도서관 색인 카드 시스템과 유사. "취득세"를 검색하면 학습된 연관어 "매수세", "부동산 구입세"도 함께 활성화된다 |
| **ColBERT** (토큰별 벡터) | 문장 내 각 토큰(단어)마다 별도 벡터를 생성하고, 질의의 각 토큰과 문서의 각 토큰 간 최대 유사도를 합산 | 두 문장을 단어 단위로 하나하나 짝지어 비교하는 것. "집 살 때 세금"의 "집"은 문서에서 "주택"과, "세금"은 "취득세"와 개별 매칭된다 |

**Multi-Stage Retrieval Pipeline**이란 이 3종 벡터를 단계적으로 활용하는 검색 전략이다:

```
[Stage 1: Prefetch — 후보 대량 수집 (병렬 실행)]
├── Dense 검색 → top-100 후보
└── Sparse 검색 → top-100 후보

[Stage 2: Fusion — 후보 합산]
└── RRF(Reciprocal Rank Fusion)로 두 리스트 합산 → top-50

[Stage 3: Rerank — 정밀 재정렬]
└── ColBERT late interaction으로 top-50을 재정렬 → top-10 반환
```

**RRF(Reciprocal Rank Fusion)란?**
두 개 이상의 랭킹 리스트를 합산하는 방법이다. 각 문서의 최종 점수는:

```
RRF_score(d) = Σ 1 / (k + rank_i(d))
```

여기서 `k`는 상수(기본 60), `rank_i(d)`는 i번째 리스트에서 문서 d의 순위다. 핵심은 **점수의 절대값이 아니라 순위(rank)를 기준으로 합산**한다는 것이다.

**비유**: 두 명의 심사위원이 각각 100명의 가수를 순위 매겼다고 하자. 한 심사위원은 100점 만점에 92점을 줬고, 다른 심사위원은 10점 만점에 8점을 줬다. 점수를 직접 더하면(92+8=100) 불공평하다. RRF는 "첫 번째 심사위원이 3위, 두 번째 심사위원이 5위에 놓았으니 종합 순위를 계산하자"는 접근이다.

### 2-2. Qdrant 컬렉션 스펙 변경

```python
# 현재 (Dense만)
client.create_collection(
    collection_name="domain_ontology",
    vectors_config={
        "dense": VectorParams(size=1024, distance=Distance.COSINE),
    },
)

# 개선 후 (Dense + Sparse + ColBERT)
client.create_collection(
    collection_name="domain_ontology_v2",
    vectors_config={
        "dense": VectorParams(size=1024, distance=Distance.COSINE),
        "colbert": VectorParams(
            size=1024,
            distance=Distance.COSINE,
            multivector_config=MultiVectorConfig(
                comparator=MultiVectorComparator.MAX_SIM,
            ),
        ),
    },
    sparse_vectors_config={
        "sparse": SparseVectorParams(
            index=SparseIndexParams(on_disk=False),
        ),
    },
)
```

### 2-3. 검색 쿼리 구조 (Qdrant Query API)

```python
results = client.query_points(
    collection_name="domain_ontology_v2",
    prefetch=[
        # Stage 1a: Dense 후보 수집
        Prefetch(query=dense_vector, using="dense", limit=100),
        # Stage 1b: Sparse 후보 수집
        Prefetch(query=sparse_vector, using="sparse", limit=100),
    ],
    # Stage 2: RRF 퓨전 → Stage 3: ColBERT 리랭킹
    query=colbert_vectors,  # 토큰별 벡터 리스트
    using="colbert",
    limit=10,
)
```

### 2-4. 기대 효과

| 현재 | 개선 후 (추정) | 근거 |
|------|--------------|------|
| 평균 Top-1 score: 0.611 | **0.75~0.80** | BGE-M3 공식 벤치마크에서 triple-vector 사용 시 단일 Dense 대비 +15~25% |
| Precision@3: 80% | **88~92%** | Sparse가 어휘 매칭 보강, ColBERT가 정밀 재정렬 |

### 2-5. 구현 계획

| 단계 | 작업 | 사용 모델/도구 |
|------|------|--------------|
| A | BGE-M3에서 3종 벡터 동시 추출하도록 embedder.py 수정 | KURE-v1 (GPU) |
| B | Qdrant 컬렉션 v2 스키마로 재생성 | Qdrant API |
| C | 3종 벡터 upsert (index_phase2.py 수정) | GPU + Qdrant |
| D | search_test_phase2.py를 multi-stage pipeline으로 수정 | Python |
| E | 기존 테스트 10개 질의로 성능 비교 | — |

### 2-6. 해결하는 약점

- **W2 (추상 질의)**: Sparse 벡터가 "집"→"주택", "세금"→"취득세" 어휘 확장 수행
- **W4 (Top-1 점수)**: ColBERT 토큰별 매칭이 세밀한 의미 비교로 점수 대폭 향상

### 2-7. 참고 자료

- BGE-M3 + Qdrant 구현 샘플 — https://github.com/yuniko-software/bge-m3-qdrant-sample
- Qdrant Hybrid Search 가이드 — https://qdrant.tech/articles/hybrid-search/
- Qdrant ColBERT Multi-Vector 문서 — https://qdrant.tech/documentation/fastembed/fastembed-colbert/

---

## 3. LLM Query Decomposition — Cross-Domain 질의 분해

### 3-1. 개념 설명

**Query Decomposition**은 복잡한 질의를 LLM이 여러 개의 단순한 서브 질의(sub-query)로 분해한 뒤, 각각을 별도로 검색하고 결과를 합산하는 기법이다.

**비유**: "경매 낙찰되면 세금 내야해?"라는 질문은 마치 병원에서 "배도 아프고 머리도 아파요"라고 말하는 것과 같다. 의사(시스템)가 이를 "복부 증상"과 "두통 증상"으로 나누어 각각 전문 진료를 하듯, 시스템도 질의를 도메인별로 분리해서 각 분야에서 최적의 결과를 가져온다.

**연구 근거**:
- **TIDE (Triple-Inspired Decomposition, ACL 2025)**: 질의에서 엔티티(entity)와 관계(relation)를 트리플(주어-관계-목적어) 형태로 추출하여 분해. 단순 분해보다 핵심 정보 보존율이 높음.
- **DO-RAG (Domain-Oriented RAG)**: LLM 기반 인텐트 분석기가 질의를 구조적으로 분해하고, 각 서브 질의를 지식 그래프와 벡터 스토어에서 동시에 검색.
- **MA-RAG (Multi-Agent RAG, 2025)**: 도메인별 전문 에이전트가 협력적 사고 체인(chain-of-thought)으로 각 측면을 처리.

### 3-2. 적용 예시

```
[예시 1: Cross-domain 질의]
입력: "경매 낙찰되면 세금 내야해?"

LLM 분해 결과:
  sub_q1: "부동산 경매 낙찰 절차와 낙찰자 의무"        → 경매 브랜치
  sub_q2: "경매 낙찰 부동산의 취득세 세율과 납부 기한"   → 세금 브랜치
  sub_q3: "경매로 취득한 부동산의 양도소득세 과세 여부"   → 세금 브랜치

검색: 각 sub_q를 domain_ontology + legal_docs에서 개별 검색
합산: 3개 결과 리스트를 RRF로 합산, 중복 제거 → 최종 top-10

[예시 2: 추상적 질의]
입력: "집 살 때 세금 얼마야?"

LLM 분해 결과:
  sub_q1: "주택 매매 시 취득세 세율"                    → 세금/취득세
  sub_q2: "주택 취득 시 부대비용 (등록면허세, 교육세)"    → 세금/기타
  sub_q3: "아파트 매수 시 중개수수료와 법무사 비용"       → 계약/거래

[예시 3: 단순 질의 — 분해 불필요]
입력: "종부세 기준 금액"

LLM 판단: 단일 도메인 질의 → 분해 없이 원본 그대로 검색
```

### 3-3. 분해 판단 로직

모든 질의를 분해하면 불필요한 LLM 호출이 발생한다. 다음 기준으로 **분해 필요 여부를 먼저 판단**한다:

```
[분해 필요 조건 — 하나라도 해당하면 분해]
1. 질의에 2개 이상의 도메인 키워드 포함 (예: "경매" + "세금")
2. 질의가 인과/조건 관계 포함 (예: "~하면 ~해야해?", "~할 때 ~은?")
3. 질의 길이가 15자 이상이면서 복수의 의문점 포함

[분해 불필요 — 원본 그대로 검색]
1. 단일 개념 질의 (예: "종부세 기준", "DSR이 뭐야")
2. 용어 정의 질의 (예: "LTV란?")
```

### 3-4. 구현 계획

| 단계 | 작업 | 사용 모델 |
|------|------|----------|
| A | 분해 필요 여부 판단 프롬프트 설계 | **Claude 4.6 Sonnet** (경량 판단, 빠른 응답) |
| B | 질의 분해 프롬프트 설계 (few-shot 10예시) | **Claude 4.6 Opus** (정확한 도메인 이해 필요) |
| C | 서브 질의별 병렬 검색 + RRF 합산 로직 구현 | Python (비동기) |
| D | 테스트 질의 20개로 분해 품질 평가 | — |

### 3-5. 해결하는 약점

- **W1 (Cross-domain)**: "경매 + 세금"이 각각 올바른 브랜치에서 검색 → **완전 해결**
- **W2 (추상 질의)**: "집 살 때 세금"이 "취득세 세율"로 구체화 → top-1 정확도 향상

### 3-6. 참고 자료

- TIDE: Triple-Inspired Decomposition (ACL 2025) — https://arxiv.org/abs/2507.00355
- DO-RAG: Domain-Specific QA Framework — https://www.techrxiv.org/users/926184/articles/1297756
- MA-RAG: Multi-Agent RAG — https://arxiv.org/pdf/2505.20096
- MultiHop-RAG Benchmark — https://openreview.net/forum?id=t4eB3zYWBK

---

## 4. Table Context Enrichment — table_fact 맥락 복원

### 4-1. 개념 설명

현재 legal_docs의 `table_fact` 청크(577개)는 표의 **행(row) 하나를 독립적으로 분리**하여 임베딩한다. 이 방식의 문제는 "이 행이 어떤 표에 속하는지, 열(column) 헤더가 무엇인지"라는 맥락이 사라진다는 것이다.

**비유**: 엑셀 표에서 셀 하나만 복사해서 메모장에 붙여넣으면 "8%"라는 숫자만 남는다. 이것이 취득세율인지 이자율인지 할인율인지 알 수 없다. Table Context Enrichment는 이 셀에 "이 값은 '다주택자 취득세 중과세율 표'의 '2주택(조정대상지역)' 행, '세율' 열에 해당하는 값입니다"라는 맥락을 복원하는 작업이다.

**연구 근거**:
- **Topo-RAG (arXiv, 2026. 1)**: 텍스트와 표를 분리된 경로(dual-path)로 검색. 표에는 Cell-Aware Late Interaction을 적용하여 셀의 공간적/구조적 관계를 보존. 결과: **nDCG@10 +18.4%**.
- **TabRAG (EMNLP 2025)**: 표를 마크다운으로 평탄화(flatten)하지 않고, 행-열 구조를 보존하는 구조적 언어 표현(structured language representation)으로 변환.
- **HD-RAG**: 계층적 표(hierarchical table)를 표 수준, 섹션 수준, 셀 수준의 3단계 메모리 인덱스로 구축.

### 4-2. 적용 예시

```
[현재 table_fact — 맥락 없음]
임베딩 텍스트: "세금 > 취득세\n\n2주택(조정대상지역), 8%"

[개선 후 — 맥락 복원]
임베딩 텍스트:
"[표 제목] 다주택자 취득세 중과세율
[열 구조] 주택 수 및 지역 | 기본세율 | 중과세율 | 비고
[소속 섹션] 제3장 취득세 중과세 > 3-2. 다주택자 중과
[행 데이터] 2주택(조정대상지역) | 1~3% | 8% | 지방세법 제13조의2"
```

### 4-3. 추가 전략: 표 단위 질문 생성

각 표에 대해 LLM으로 해당 표가 답할 수 있는 **자연어 질문 3~5개**를 생성하고, 이를 별도 검색 대상(hyde와 유사한 역할)으로 색인한다.

```
[표: 다주택자 취득세 중과세율]
생성된 질문:
  Q1: "2주택자 조정대상지역 취득세는 몇 퍼센트인가요?"
  Q2: "3주택 이상 보유자의 취득세 중과세율은?"
  Q3: "비조정지역 2주택자도 취득세 중과 대상인가요?"
  Q4: "법인이 주택을 취득하면 취득세가 얼마인가요?"
```

### 4-4. 구현 계획

| 단계 | 작업 | 사용 모델 |
|------|------|----------|
| A | legal_docs의 table_fact 577개에 대해 표 맥락(제목, 열 헤더, 소속 섹션) 추출 | **Claude 4.6 Sonnet** (정형 작업, 대량 처리) |
| B | 표 단위 자연어 질문 생성 (고유 표 수 × 3~5개) | **Claude 4.6 Sonnet** |
| C | 생성 품질 검수 (샘플 30개) | **Claude 4.6 Opus** (정확성 검증) |
| D | 맥락 보강된 table_fact 재임베딩 + 질문 청크 추가 색인 | KURE-v1 (GPU) |

### 4-5. 해결하는 약점

- **W3 (table_fact 맥락 손실)**: 열 헤더 + 표 제목 + 섹션 정보 복원 → **직접 해결**
- **W4 (Top-1 점수)**: 맥락이 풍부해져 질의-청크 간 의미 매칭 정밀도 향상

### 4-6. 참고 자료

- Topo-RAG — https://arxiv.org/abs/2601.10215
- TabRAG (EMNLP 2025) — https://openreview.net/forum?id=T4aApVYr7x
- HD-RAG — https://arxiv.org/html/2504.09554v1
- TARGET: Table Retrieval Benchmark — https://arxiv.org/abs/2505.11545

---

## 5. Cross-Encoder Reranking — 최종 정밀도 강화

### 5-1. 개념 설명

**Cross-Encoder**는 질의(query)와 문서(document)를 **하나의 입력으로 합쳐서** 트랜스포머 모델에 통과시키고, 직접 관련도 점수를 출력하는 모델이다.

이전 단계(Dense, Sparse, ColBERT)의 검색 모델들은 모두 **Bi-Encoder** 방식이다. Bi-Encoder는 질의와 문서를 **각각 따로** 벡터로 변환한 뒤 코사인 유사도 등으로 비교한다. 이 방식은 빠르지만(문서 벡터를 미리 계산해 놓을 수 있으므로), 질의와 문서 간의 **세밀한 상호작용**을 놓칠 수 있다.

**비유**:
- **Bi-Encoder**: 두 사람의 프로필(이력서)을 각각 읽고 "이 두 사람이 잘 맞을까?" 판단하는 것. 빠르지만 얕다.
- **Cross-Encoder**: 두 사람을 실제로 한 방에 앉혀놓고 대화를 시킨 뒤 "이 두 사람이 잘 맞는가?" 판단하는 것. 느리지만 정확하다.

그래서 Cross-Encoder는 전체 컬렉션을 검색하는 데는 사용할 수 없고(너무 느림), **이미 검색된 top-20~50 후보에 대해서만 재정렬(reranking)**하는 용도로 사용한다.

### 5-2. 추천 모델

| 모델 | 파라미터 수 | 한국어 지원 | 특징 |
|------|-----------|-----------|------|
| **`BAAI/bge-reranker-v2-m3`** | ~568M | 다국어 (한국어 포함) | BGE-M3 생태계와 호환, KURE-v1과 함께 사용 시 시너지 |
| `jina-reranker-v2-base-multilingual` | ~278M | 다국어 | 경량, 빠른 추론 |

### 5-3. 파이프라인 내 위치

```
[전체 검색 파이프라인]

사용자 질의
  ↓
[선택적] Query Decomposition (섹션 3)     ← LLM
  ↓
Stage 1: Dense + Sparse prefetch (top-100 × 2)  ← 벡터 DB
  ↓
Stage 2: RRF 퓨전 (top-50)                       ← 알고리즘
  ↓
Stage 3: ColBERT 리랭킹 (top-20)                  ← 벡터 DB
  ↓
Stage 4: Cross-Encoder 리랭킹 (top-10)   ← GPU 모델 추론
  ↓
최종 결과 (top-5~10)
```

### 5-4. 기대 효과

Cross-Encoder 리랭킹은 일반적으로 **최종 precision +5~10%** 향상을 가져온다. 다만 이미 ColBERT 리랭킹을 거친 후이므로 추가 개선 폭은 상대적으로 작다. 비용 대비 효과를 고려해 **고가치 질의(세율/규제 관련)**에만 선택적으로 적용하는 것도 방법이다.

### 5-5. Harvey AI 사례 참고

법률 AI 분야 선두 기업인 Harvey AI의 검색 아키텍처에서 주목할 점:

1. **법률 코퍼스에 fine-tuned 임베딩**: 범용 임베딩 모델 대비 **법률 검색에서 30% 성능 향상** 달성. 우리 시스템도 장기적으로 KURE-v1을 부동산 법률 코퍼스에 fine-tuning하면 유사한 효과를 기대할 수 있다.

2. **비의미적 신호(non-semantic signals) 활용**: 문서의 최신성(recency), 관할권(jurisdiction), 문서 유형(doc_type) 등을 랭킹에 반영. 예를 들어:
   - 세법은 매년 개정되므로 **최신 문서에 가산점**
   - 지역 규제 질의 시 **해당 지역 문서를 필터링**
   - 법령 원문 > 해설서 > 블로그 순으로 **신뢰도 가중치**

3. **3-tier 데이터 구조**: 사용자 업로드 문서, 장기 보관 문서, 제3자 법률 DB를 분리 관리. 우리 시스템의 domain_ontology(용어) + legal_docs(법령) + notes_rag(유튜브 해설) 3단 구조와 유사.

### 5-6. 해결하는 약점

- **W4 (Top-1 점수)**: 최종 정밀도 +5~10% 추가 향상

### 5-7. 참고 자료

- Harvey AI Retrieval Architecture — https://www.harvey.ai/blog/biglaw-bench-retrieval
- Harvey AI System Design (ZenML) — https://www.zenml.io/llmops-database/enterprise-grade-rag-systems-for-legal-ai-platform
- Qdrant Reranking Tutorial — https://qdrant.tech/documentation/advanced-tutorials/reranking-hybrid-search/

---

## 6. Intent Classifier + Query Router — 질의 사전 분류

### 6-1. 개념 설명

**Intent Classification**은 사용자 질의의 **의도(intent)**를 먼저 분류하고, **슬롯(slot)**에서 핵심 엔티티를 추출한 뒤, 분류 결과에 따라 검색 전략을 달리하는 기법이다.

**비유**: 대형 병원의 접수 창구와 같다. 환자가 "배가 아파요"라고 하면 접수 직원이 "소화기내과"로 안내한다. 모든 진료과에 환자를 보내지 않고, 가장 적합한 진료과로 바로 라우팅하는 것이다. 마찬가지로, "집 살 때 세금"이라는 질의가 들어오면 "세금 도메인"으로 라우팅하여 세금 브랜치에서 우선 검색한다.

**연구 근거**:
- **REIC (RAG-Enhanced Intent Classification, KDD 2025)**: RAG를 활용하여 인텐트 분류에 필요한 맥락 예시를 동적으로 검색. 전통적 fine-tuning 대비 적은 학습 데이터로도 높은 분류 정확도 달성.
- **RAGRouter (2025)**: 경량 신경망 분류기로 질의별 최적 데이터 소스를 동적 선택.

### 6-2. 인텐트·슬롯 설계

```
[인텐트 (6종)]
- 세금_문의:     세율, 비과세, 감면, 납부 관련
- 대출_규제:     LTV, DSR, 금리, 대출 한도 관련
- 경매_절차:     입찰, 낙찰, 배당, 명도 관련
- 청약_분양:     가점, 당첨, 자격, 특별공급 관련
- 시세_투자:     시세, 전망, 수익률, 입지 관련
- 정책_규제:     규제지역, 전매제한, 실거주 의무 관련

[슬롯 (4종)]
- 지역:         서울, 강남구, 조정대상지역 등
- 부동산_유형:   아파트, 오피스텔, 토지, 상가 등
- 거래_유형:     매매, 전세, 경매, 상속, 증여 등
- 세금_유형:     취득세, 양도세, 종부세, 재산세 등
```

### 6-3. 적용 예시

```
입력: "집 살 때 세금 얼마야?"

분류 결과:
  intent: 세금_문의
  slots:  { 거래_유형: "매매", 세금_유형: null }

검색 전략:
  1. domain_ontology에서 branch IN ["tax"] 필터 적용 → 세금 용어만 검색
  2. 필터 내 top-5 결과: "취득세"가 top-1으로 상승 (경쟁 브랜치 제거됨)
  3. legal_docs에서 part_title LIKE "%취득%" 필터 추가 적용
```

```
입력: "경매 낙찰되면 세금 내야해?"

분류 결과:
  intent: [경매_절차, 세금_문의]  ← 복수 인텐트 감지
  slots:  { 거래_유형: "경매" }

검색 전략:
  → Query Decomposition(섹션 3) 트리거 → 서브 질의로 분해 후 각 브랜치 검색
```

### 6-4. 구현 계획

| 단계 | 작업 | 사용 모델 |
|------|------|----------|
| A | 인텐트 분류 프롬프트 설계 (few-shot 20예시) + 슬롯 추출 | **Claude 4.6 Sonnet** (빠른 응답, 분류 작업에 충분) |
| B | 평가 데이터셋 구축 (100개 질의 + 정답 레이블) | **Claude 4.6 Opus** (정답 레이블 품질 보장) |
| C | Qdrant 메타데이터 필터 연동 로직 구현 | Python |
| D | 복수 인텐트 감지 시 Query Decomposition 자동 트리거 연동 | Python |

### 6-5. 해결하는 약점

- **W1 (Cross-domain)**: 복수 인텐트 감지 → 자동 분해 트리거
- **W2 (추상 질의)**: 인텐트 기반 브랜치 필터링으로 노이즈 제거

### 6-6. 참고 자료

- REIC (KDD 2025) — https://arxiv.org/pdf/2506.00210
- RAGRouter — https://arxiv.org/abs/2505.23052

---

## 7. Ontology Graph + RAPTOR — 구조적 확장 (중장기)

### 7-1. OG-RAG: 온톨로지 기반 하이퍼그래프 (Microsoft, EMNLP 2025)

**개념**: 일반적인 그래프에서 하나의 간선(edge)은 두 노드만 연결한다. **하이퍼그래프(hypergraph)**에서는 하나의 **하이퍼엣지(hyperedge)**가 **여러 노드를 동시에 연결**할 수 있다. OG-RAG는 도메인 온톨로지를 기반으로 관련 팩트(fact)들을 하이퍼엣지로 묶고, 질의에 대해 최소한의 하이퍼엣지 집합을 검색한다.

**비유**: 일반 그래프가 "A와 B는 친구"라는 1:1 관계만 표현한다면, 하이퍼그래프는 "A, B, C, D는 같은 동아리 멤버"라는 그룹 관계를 표현할 수 있다. 부동산 도메인에서 "경매 낙찰 → 취득세 → 등기비용 → 법무사 수수료"를 하나의 하이퍼엣지로 묶으면, "경매 낙찰" 하나만 검색해도 관련 세금·비용 정보가 함께 검색된다.

**성과**: +55% fact recall, +40% response correctness, +27% reasoning accuracy (기존 RAG 대비)

**적용 방안**:
현재 온톨로지의 `related_terms` 필드를 하이퍼엣지로 확장:
```json
{
  "hyperedge_id": "he_auction_tax_flow",
  "description": "경매 낙찰 시 발생하는 세금 및 비용 흐름",
  "members": [
    "auction_winning_bid",       // 경매 브랜치
    "tax_acquisition",            // 세금 브랜치
    "registration_transfer",      // 등기 브랜치
    "contract_settlement_cost"    // 계약 브랜치
  ],
  "context": "경매 낙찰자는 낙찰대금 외에 취득세(1~12%), 등기이전비용,
              법무사 수수료를 추가로 부담해야 한다."
}
```

### 7-2. RAPTOR: 재귀적 계층 요약 (Stanford, ICLR 2024)

**개념**: 문서 청크들을 의미적으로 클러스터링한 뒤, 각 클러스터의 **요약(summary)**을 생성하고, 이 요약들을 다시 클러스터링하여 더 상위의 요약을 생성하는 과정을 재귀적으로 반복한다. 결과적으로 **트리(tree) 구조**가 만들어진다.

**비유**: 대학 교재의 구조와 같다.
- 잎 노드(leaf): 교재의 각 문단 (구체적 사실)
- 중간 노드: 각 절(section)의 요약
- 루트 노드: 각 장(chapter)의 요약

학생이 "부동산 세금 전체 구조가 뭐야?"라는 추상적 질문을 하면 장(chapter) 수준의 요약 노드에서 답을 찾고, "2주택자 조정대상지역 취득세 세율은?"이라는 구체적 질문을 하면 문단(leaf) 수준에서 답을 찾는다.

**적용 방안** — legal_docs 976 청크에 적용:
```
[Level 0 — Leaf] 976개 원본 청크
  ↓ 클러스터링 (k-means on embeddings)
[Level 1 — Section Summary] ~50개 섹션 요약
  예: "취득세 중과세율 관련 조항 요약: 다주택자, 법인, 조정대상지역별 세율..."
  ↓ 클러스터링
[Level 2 — Chapter Summary] ~10개 장 요약
  예: "취득세 전체 구조: 기본세율(1~3%), 중과(8~12%), 감면, 신고납부 절차..."
  ↓
[Level 3 — Root] 1개 전체 요약
  예: "2025 주택과 세금: 취득~보유~양도 단계별 세금 체계 총정리"
```

검색 시에는 **모든 레벨의 노드를 함께 검색** 대상으로 포함한다. 추상적 질의는 상위 노드에 매칭되고, 구체적 질의는 하위 노드에 매칭된다.

### 7-3. 구현 계획

| 단계 | 작업 | 사용 모델 | 비고 |
|------|------|----------|------|
| A | 하이퍼엣지 정의 (cross-domain 관계 30~50개) | **Claude 4.6 Opus** (도메인 전문성, 정확한 관계 설계 필요) |  |
| B | 하이퍼엣지 Qdrant 색인 (별도 컬렉션 또는 페이로드) | KURE-v1 + Qdrant | |
| C | RAPTOR 클러스터링 + 요약 생성 (Level 1~3) | **Claude 4.6 Sonnet** (요약 생성 대량 작업) | ~60개 요약 생성 |
| D | 요약 노드 색인 + 검색 파이프라인 통합 | KURE-v1 + Qdrant | |

### 7-4. 해결하는 약점

- **W1 (Cross-domain)**: 하이퍼엣지가 브랜치를 횡단하는 관계를 명시적으로 인코딩
- **W2 (추상 질의)**: RAPTOR 상위 노드가 추상적 질의의 착지점 역할

### 7-5. 참고 자료

- OG-RAG — https://arxiv.org/abs/2412.15235
- OG-RAG GitHub — https://github.com/microsoft/ograg2
- RAPTOR — https://arxiv.org/abs/2401.18059
- RAPTOR GitHub — https://github.com/parthsarthi03/raptor
- GraphRAG Survey — https://arxiv.org/abs/2408.08921
- Awesome-GraphRAG — https://github.com/DEEP-PolyU/Awesome-GraphRAG

---

## 8. 종합 우선순위 로드맵

### 8-1. 영향도-난이도 매트릭스

```
                        영향도 높음
                            │
       ┌────────────────────┼────────────────────┐
       │  [P0] Contextual   │  [P3] KURE-v1      │
       │       Retrieval    │       Domain        │
       │                    │       Fine-tuning   │
       │  [P0] BGE-M3       │                     │
       │       Triple-Vec   │  [P3] RAPTOR        │
       │                    │       계층 요약       │
  난이도├────────────────────┼────────────────────┤ 난이도
  낮음 │  [P1] Query        │  [P2] OG-RAG        │ 높음
       │       Decomposition│       하이퍼그래프    │
       │                    │                     │
       │  [P1] Table Context│  [P3] Topo-RAG      │
       │       Enrichment   │       Dual-path     │
       │                    │                     │
       │  [P2] Cross-Encoder│                     │
       │       Reranking    │                     │
       │                    │                     │
       │  [P2] Intent       │                     │
       │       Classifier   │                     │
       └────────────────────┼────────────────────┘
                            │
                        영향도 낮음
```

### 8-2. 실행 순서 및 예상 효과 누적

| 순서 | 개선 항목 | 예상 Precision@3 | 예상 평균 Top-1 | 비고 |
|------|---------|-----------------|----------------|------|
| 현재 | — | 80% | 0.611 | 5_phase2_search_test_report.md 기준 |
| **P0-a** | Contextual Retrieval | 85~88% | 0.70~0.73 | 맥락 prefix로 의미 거리 단축 |
| **P0-b** | BGE-M3 Triple-Vector | 88~92% | 0.75~0.80 | Sparse + ColBERT 추가 |
| **P1-a** | Query Decomposition | 92~95% | 0.80~0.83 | Cross-domain 완전 해결 |
| **P1-b** | Table Context Enrichment | 93~95% | 0.82~0.85 | table_fact 정밀도 향상 |
| **P2** | Intent Classifier + Cross-Encoder | 95~97% | 0.85~0.88 | 최종 정밀도 마무리 |
| **P3** | RAPTOR + OG-RAG | 97%+ | 0.88~0.92 | 구조적 완성 |

### 8-3. 사용 모델 정책

| 모델 | 용도 | 비용 특성 |
|------|------|----------|
| **Claude 4.6 Opus** | 온톨로지 관계 설계, 품질 검수, 평가 데이터 생성, Query Decomposition 프롬프트 설계 등 **정확성·전문성이 핵심**인 작업 | 고비용, 소량 정밀 작업 |
| **Claude 4.6 Sonnet** | 맥락 prefix 배치 생성, 표 질문 생성, 인텐트 분류, 요약 생성 등 **패턴이 정형화되고 대량 처리**가 필요한 작업 | 저비용, 대량 배치 작업 |

---

## 9. 핵심 참고 문헌 목록

| 분야 | 논문/프로젝트 | 출처 | 핵심 기여 |
|------|-------------|------|----------|
| Contextual Retrieval | Anthropic (2024) | anthropic.com | 맥락 prefix로 검색 실패 -67% |
| Hybrid Search | BGE-M3 + Qdrant | github.com/yuniko-software | Dense+Sparse+ColBERT 통합 |
| Query Decomposition | TIDE (ACL 2025) | arxiv.org/abs/2507.00355 | 트리플 기반 질의 분해 |
| Table Retrieval | Topo-RAG (2026) | arxiv.org/abs/2601.10215 | Dual-path 표 검색 +18% |
| Reranking | bge-reranker-v2-m3 | huggingface.co/BAAI | 다국어 Cross-Encoder |
| Ontology Graph | OG-RAG (EMNLP 2025) | arxiv.org/abs/2412.15235 | 하이퍼그래프 +55% recall |
| Hierarchical RAG | RAPTOR (ICLR 2024) | arxiv.org/abs/2401.18059 | 재귀적 요약 트리 |
| Legal RAG | Harvey AI | harvey.ai | Fine-tuned 임베딩 +30% |
| Intent Classification | REIC (KDD 2025) | arxiv.org/abs/2506.00210 | RAG 기반 인텐트 분류 |
| Domain RAG | DO-RAG | techrxiv.org | 도메인 특화 QA 프레임워크 |
