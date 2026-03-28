# LLM Query Decomposition — Cross-Domain 질의 분해 상세 계획

> 작성일: 2026-03-27
> 선행 문서: `06_results_and_analysis.md`, `10_expanded_benchmark_results.md`
> 대상: `6_search_improvement_research.md` § 3. LLM Query Decomposition
> 목적: 극단적 구어체 질의 2개 해결 + Cross-Domain 질의 검색 품질 향상

---

## 0. 배경 및 동기

### 0-1. Phase 2 검색 성능 궤적

Phase 2에서 검색 품질을 단계적으로 개선해 왔다:

```
Precision@3 궤적:
  Baseline (Phase 2 초기):       80%   (8/10)
  + Contextual Retrieval (P0-a):  90%   (+10%p)
  + BGE-M3 D+S RRF (P0-b):      92%   (+2%p)   ← 현재 운영 (Setting C)
  + Cross-Encoder (Setting E):   76%   (-16%p)  ← 미채택 (성능 하락)
  + 3-Way RRF (Setting F):      88%   (-4%p)   ← 미채택 (근접하나 미달)
```

### 0-2. 해결 대상 — 여전히 실패하는 2개 질의

현재 Setting C (Dense+Sparse RRF, P@3=92%)에서도 해결되지 않는 질의가 **2개** 있다:

| 질의 | 검색 결과 (Top-1) | 기대 키워드 | 실패 원인 |
|------|------------------|-----------|----------|
| "부동산 사면 나라에 돈 내야 되나" | 공과금 | 취득세, 세금 | "나라에 돈" ↔ "취득세" 의미 격차 |
| "은행에서 집값의 몇 프로까지 빌려주는지" | 시장이자율 | LTV, 담보, 대출 | "빌려주는" ↔ "LTV" 개념 격차 |

> **쉬운 비유 — 외국인에게 길 묻기:**
>
> "큰 건물 옆에 동그란 것 나오는 데 어디야?"라고 물었을 때, 사람은 "ATM"이나 "은행"을 떠올릴 수 있지만, 검색 엔진은 "동그란 것"이라는 단어만 보고 "시계", "거울" 같은 엉뚱한 결과를 반환한다. **Query Rewriting**은 이 질문을 "ATM 위치"로 바꿔주는 통역사 역할이다.

### 0-3. Cross-Encoder도 해결 못한 이유

Setting E(Cross-Encoder Reranking)에서도 이 2개 질의는 실패했다 (`10_expanded_benchmark_results.md` §2-2):

- "부동산 사면 나라에 돈 내야 되나" → CE 결과: **국세** (Top-1, score 0.4505) — 여전히 취득세 도달 실패
- "은행에서 집값의 몇 프로까지 빌려주는지" → CE 결과: **임차료** (Top-1, score 0.0000) — LTV 연결 완전 실패

> **쉬운 비유 — 왜 Cross-Encoder도 실패하는가:**
>
> Cross-Encoder는 "주어진 후보 중에서 가장 적합한 것"을 골라내는 심사위원이다. 하지만 1차 검색(RRF)이 후보 50개를 뽑을 때 "취득세"가 아예 포함되지 않으면, 아무리 뛰어난 심사위원이라도 정답을 고를 수 없다. **질의 자체를 바꿔야** 올바른 후보가 1차 검색에 들어온다.

### 0-4. 결론: Query Rewriting + Decomposition이 유일한 해법

| 접근법 | 실패 질의 2개 해결? | 이유 |
|--------|------------------|------|
| Contextual Retrieval (P0-a) | X | 문서 쪽에 다리를 놓았지만, "나라에 돈"과 "취득세"는 여전히 너무 멀다 |
| BGE-M3 Sparse (P0-b) | X | 학습된 동의어 확장도 "나라에 돈"→"취득세" 매핑은 커버하지 못한다 |
| Cross-Encoder (Setting E) | X | 후보 자체에 정답이 없으므로 리랭킹으로 해결 불가 |
| **Query Rewriting (P1-a)** | **O** | 질의를 "부동산 취득 시 취득세 납부"로 변환하면 정답이 후보에 포함된다 |

---

## 1. Query Decomposition이란?

### 1-1. 핵심 개념

**Query Decomposition**은 사용자의 복잡한 질의를 LLM(대규모 언어 모델)이 여러 개의 단순한 **서브 질의(sub-query)**로 분해한 뒤, 각각을 별도로 검색하고 결과를 합산하는 기법이다.

> **쉬운 비유 — 병원 진료:**
>
> 환자가 "배도 아프고 머리도 아파요"라고 말하면, 의사는 이를 "복부 증상"과 "두통 증상"으로 나누어 각각 전문 진료를 한다. 복부는 내과로, 두통은 신경과로 보내서 각 분야의 전문 의사가 진단한다. 마찬가지로, "경매 낙찰되면 세금 내야해?"라는 질문은 "경매 절차"와 "취득세 납부"라는 두 전문 분야에 걸쳐 있으므로, 각각 분리해서 검색하면 더 정확한 결과를 얻을 수 있다.

### 1-2. 본 프로젝트에서의 두 가지 기능

이 프로젝트에서는 Query Decomposition을 두 가지 목적으로 활용한다:

| 기능 | 목적 | 해결 약점 | 예시 |
|------|------|----------|------|
| **Query Rewriting** | 구어체 → 전문용어 변환 | W2 (추상 질의) | "나라에 돈 내야 되나" → "취득세 납부 의무" |
| **Query Decomposition** | 복합 질의 → 서브 질의 분리 | W1 (Cross-domain) | "경매 낙찰되면 세금?" → ① 경매 절차 ② 취득세 |

두 기능을 **하나의 LLM 호출**로 동시에 처리한다.

### 1-3. 적용 예시

```
[예시 1: REWRITE — 구어체 변환]
입력: "부동산 사면 나라에 돈 내야 되나"

LLM 분석:
  type: REWRITE
  reasoning: "구어체 '나라에 돈 내야'는 취득세 납부를 의미하는 비공식 표현"
  queries:
    ① "부동산 취득 시 취득세 납부 의무와 세율"  → 세금 브랜치

검색: 변환된 질의로 domain_ontology + legal_docs 검색
결과: 취득세가 Top-1에 등장

[예시 2: DECOMPOSE — Cross-domain 분리]
입력: "경매 낙찰되면 세금 내야해?"

LLM 분석:
  type: DECOMPOSE
  reasoning: "경매 절차(경매 도메인)와 취득세 납부(세금 도메인) 2개 영역에 걸침"
  queries:
    ① "부동산 경매 낙찰 절차와 낙찰자 의무"     → 경매 브랜치
    ② "경매 낙찰 부동산의 취득세 세율과 납부"    → 세금 브랜치

검색: 각 서브 질의를 개별 검색 → RRF로 합산
결과: 경매 관련 + 세금 관련 결과가 모두 포함

[예시 3: SIMPLE — 변환 불필요]
입력: "종부세 기준 금액"

LLM 분석: (사전 필터에서 처리, LLM 호출 안 함)
  type: SIMPLE
  queries:
    ① "종부세 기준 금액"  → 원본 그대로

검색: 기존 파이프라인과 동일
```

---

## 2. 학술 연구 기반

### 2-1. 핵심 논문 7편 분석

이 작업의 설계는 2024~2026년 최신 연구에 기반한다:

#### Adaptive-RAG (KAIST, 2024)

> **논문 요약:** 모든 질의에 동일한 검색 전략을 적용하는 대신, 질의의 **복잡도를 자동으로 분류**하여 적절한 전략을 선택한다.

- **핵심 기여**: T5-Large (770M 파라미터) 분류기로 질의를 3단계로 분류
  - **A단계**: 검색 불필요 (LLM 자체 지식으로 답변)
  - **B단계**: 단일 검색 (한 번의 검색으로 충분)
  - **C단계**: 다단계 검색 (여러 번 검색 필요)
- **적용점**: 우리의 SIMPLE / REWRITE / DECOMPOSE 3단 분류의 이론적 근거
- 출처: https://arxiv.org/html/2403.14403v2

> **쉬운 비유:**
>
> 도서관에 책을 찾으러 갔을 때, "해리포터 1권"은 바로 서가에서 찾으면 되고(A단계), "마법 소설 추천"은 사서에게 물어보면 되고(B단계), "중세 유럽 마법과 현대 판타지 소설의 연관성"은 여러 분야를 돌아다니며 조사해야 한다(C단계). 질문의 복잡도에 따라 전략이 달라져야 한다.

#### TIDE — Triple-Inspired Decomposition (ACL 2025)

> **논문 요약:** 질의를 단순히 키워드로 쪼개는 대신, **주어-관계-목적어 트리플**(triple) 구조를 추출하여 분해한다.

- **핵심 기여**: "경매 낙찰되면 세금 내야해?"를 트리플로 분석하면:
  - (낙찰자, 납부해야하는, 세금) → 세금 검색
  - (경매, 절차인, 낙찰) → 경매 검색
  - 단순 키워드 분할보다 **핵심 정보 보존율**이 높음
- **적용점**: 도메인 엔티티(온톨로지 term) 기반 분해 전략
- 출처: https://arxiv.org/abs/2507.00355

#### PruneRAG (2026)

> **논문 요약:** 모든 질의를 분해하면 불필요한 검색이 발생한다. **신뢰도 기반 가지치기**(confidence-guided pruning)로 단순 질의는 분해를 건너뛴다.

- **핵심 기여**:
  - LLM의 토큰별 log probability(신뢰도)가 0.95 이상이면 직접 답변 (검색 불필요)
  - 평균 검색 호출 횟수: **6.73 → 2.06** (4.9x 효율 향상)
  - Evidence Forgetting Rate 지표 도입
- **적용점**: 우리의 2단계 게이팅 (Tier 1: 룰 기반 사전 필터)의 이론적 근거

> **쉬운 비유:**
>
> 학교 시험에서 "2+3=?"은 바로 답을 쓸 수 있고, "미적분 응용 문제"는 풀이 과정이 필요하다. PruneRAG는 쉬운 문제에 긴 풀이를 쓰지 않도록 **문제 난이도를 먼저 판단**하는 것이다.

- 출처: https://arxiv.org/html/2601.11024

#### Collab-RAG (2025)

> **논문 요약:** 질의 분해에 반드시 거대 모델이 필요한 것은 아니다. **파인튜닝된 3B 모델**이 32B frozen 모델보다 분해 성능이 높다.

- **핵심 기여**: "작은 모델이 분해, 큰 모델이 합성" 전략이 비용 대비 효과적
- **적용점**: 우리 설계에서 **Sonnet**(분해/라우팅)과 **Opus**(답변 합성)를 분리하는 근거
- 출처: https://arxiv.org/abs/2504.04915

#### MA-RAG — Multi-Agent RAG (2025)

- **핵심 기여**: 4-agent 구조 (Planner → Step Definer → Extractor → QA Agent). 도메인별 전문 에이전트가 협력적 사고 체인(chain-of-thought)으로 각 측면을 처리
- **적용점**: 향후 Phase 2+ multi-agent 확장 시 참고할 구조
- 출처: https://arxiv.org/abs/2505.20096

#### DO-RAG — Domain-Oriented RAG (Tsinghua, 2025)

- **핵심 기여**: PostgreSQL + pgvector + 다층 Knowledge Graph 하이브리드로 94%+ answer relevancy 달성. LLM 기반 인텐트 분석기가 질의를 구조적으로 분해
- **적용점**: 도메인 특화 QA에서 KG + 벡터 하이브리드 접근의 유효성 확인
- 출처: https://arxiv.org/html/2505.17058v1

#### ⚠️ Scaling RAG Fusion in Production (2026.03)

> **논문 요약 (경고):** RAG Fusion의 검색 지표 개선이 프로덕션 환경(re-ranking + context budget 적용 후)에서 **대부분 소멸**한다. Hit@10이 오히려 하락하는 경우도 있다.

- **핵심 시사점**: **검색 지표만으로 판단하면 안 된다.** end-to-end (최종 답변 품질)로 평가해야 한다
- **적용점**: 벤치마크에서 Precision@3뿐 아니라 답변 생성까지 포함한 종합 평가 필요
- 출처: https://arxiv.org/abs/2603.02153

#### DecomposeRAG

- **핵심 수치**: 질의 hop 수별 분해 효과
  - 1-hop(단일 질의): +1.3% (거의 무의미)
  - 3-hop(복합 질의): **+82.2%**
  - 4+hop(고도 복합): **+156.3%**
- **적용점**: Cross-domain(2+ hop) 질의에서 분해 효과가 극대화됨을 정량 확인. **단순 질의는 분해하지 않는 것이 맞다.**

### 2-2. 프로덕션 프레임워크 참고

| 프레임워크 | 기법 | 핵심 코드 패턴 | 참고 사항 |
|-----------|------|-------------|----------|
| **LangChain** | `MultiQueryRetriever` | 3개 이상 변형 질의 생성 후 합산 | 단순 변형보다 도메인 태깅이 우리 데이터에 더 적합 |
| **LlamaIndex** | `SubQuestionQueryEngine` | 서브 질의를 각각 다른 인덱스(tool)로 라우팅 | 온톨로지/법률 컬렉션별 라우팅 아이디어 |
| **NVIDIA RAG Blueprint** | 설정 기반 on/off | `ENABLE_QUERY_DECOMPOSITION=true`, `MAX_RECURSION_DEPTH=3` | 재귀적 분해 깊이 제한 패턴 |
| **Haystack** | Pydantic 구조화 출력 | 3단계 파이프라인 (분류 → 분해 → 합산) | 구조화된 JSON 출력 패턴 |

### 2-3. Cross-Encoder(Setting E) 벤치마크 시사점

`10_expanded_benchmark_results.md`에서 얻은 핵심 발견:

| 관찰 | 설명 | P1-a 설계에 미치는 영향 |
|------|------|---------------------|
| CE가 "집 살 때 세금"→"취득세" 최초 달성 | CE score 0.9346 | **Query Rewriting 후 CE 결합(P1-b)이 유망** |
| CE 전체 P@3가 76%로 하락 | "넓은 키워드 매칭"에 약함 | RRF 기반 1차 검색은 유지해야 함 |
| 2개 실패 질의는 CE도 해결 불가 | 후보 자체에 정답 없음 | **질의 변환이 선행되어야 CE가 효과적** |

→ P1-a (Query Rewriting) 완료 후, P1-b에서 Cross-Encoder를 2차 리랭커로 재도입 예정.

---

## 3. 아키텍처 설계

### 3-1. 현재 파이프라인 (Setting C — 변경 없음)

```
User Query → BGE-M3 embed_query() → Qdrant Dense+Sparse RRF → Top-K 결과
```

> **현재 파이프라인의 한계**: 사용자가 구어체로 입력하면, 임베딩 벡터가 전문용어 벡터와 멀리 떨어져 있어 정답이 검색되지 않는다.

### 3-2. 제안 파이프라인

```
User Query
    │
    ▼
[Stage 0] 2단계 게이팅 ─────────────────────────────────────
    │
    ├── Tier 1: 룰 기반 사전 필터 (<1ms)
    │     │
    │     ├── 정규 용어 매칭 + 단일 도메인 + 짧은 질의
    │     │     → SIMPLE: 원본 그대로 검색 (LLM 호출 없음)
    │     │
    │     └── 매칭 실패 or 복합 질의
    │           → Tier 2로 전달
    │
    └── Tier 2: LLM 질의 분석 (Claude Sonnet, ~400ms)
          │
          ├── REWRITE: 정제된 단일 질의로 변환
          │     "나라에 돈 내야 되나" → "취득세 납부 의무"
          │
          └── DECOMPOSE: 2~3개 서브 질의로 분해
                "경매 낙찰되면 세금?" → ① 경매 절차 ② 취득세
    │
    ▼
[Stage 1] BGE-M3 embed_query() ─ 각 질의/서브 질의별 임베딩
    │
    ▼
[Stage 2] Qdrant hybrid_rrf 검색 ─ 기존 search_ontology/search_legal 재사용
    │
    ▼
[Stage 3] 결과 병합 ─ DECOMPOSE인 경우 RRF 합산 + 중복 제거
    │
    ▼
Final Top-K 결과
```

> **쉬운 비유 — 통역사가 있는 도서관:**
>
> 현재 시스템은 외국어(구어체)로 된 질문을 그대로 검색 엔진에 넣는 것과 같다. 제안 파이프라인은 **통역사(LLM)**를 앞에 배치하여, 외국어 질문을 도서관이 이해하는 언어(전문용어)로 번역한 후 검색하는 방식이다. 단, 이미 도서관 언어(전문용어)로 된 질문은 통역사를 거치지 않고 바로 검색한다.

### 3-3. 핵심 설계 결정 3가지

#### 결정 1: 단일 LLM 호출로 분류+변환+분해 통합

```
[기각된 방식 — 2단 호출]
질의 → 분류 LLM (SIMPLE/REWRITE/DECOMPOSE 판단) → 결과에 따라 → 변환 LLM (실제 변환)
       400ms                                                      400ms
       총 ~800ms

[채택된 방식 — 단일 호출]
질의 → 통합 LLM (판단 + 변환을 동시에)
       ~400ms
       총 ~400ms
```

**이유**: 판단과 변환을 하나의 프롬프트로 처리하면 레이턴시가 절반으로 줄어든다. Claude Sonnet의 구조화된 JSON 출력 능력이 이를 가능하게 한다.

#### 결정 2: 기존 검색 함수 100% 재사용

새 코드는 기존 `search_ontology()`, `search_legal()` 함수를 **감싸는 래퍼(wrapper)**만 구현한다. 검색 로직 자체를 수정하지 않으므로:
- Setting C의 기존 성능을 보장
- 기존 벤치마크 코드와 호환
- 롤백이 간단 (래퍼만 제거하면 원복)

#### 결정 3: 2단계 게이팅으로 LLM 호출 억제

모든 질의에 LLM을 호출하면 비용과 레이턴시가 불필요하게 증가한다. PruneRAG의 연구 결과에 따라, 단순 질의는 LLM 없이 통과시키는 사전 필터를 둔다.

목표 LLM 호출율: **≤ 60%** (40%의 단순 질의는 LLM 호출 없이 처리)

---

## 4. 비용/레이턴시 분석

### 4-1. 레이턴시 예산

> **쉬운 비유 — 식당 주문 시간:**
>
> SIMPLE 주문: "아메리카노" → 바로 제조 (35ms)
> REWRITE 주문: "그 진한 거요" → 직원이 "에스프레소 말씀이시죠?" 확인 후 제조 (435ms)
> DECOMPOSE 주문: "커피도 주고 케이크도 주세요" → 음료와 디저트를 각각 준비 (470ms)

| 구간 | SIMPLE | REWRITE | DECOMPOSE | 비고 |
|------|--------|---------|-----------|------|
| Tier 1 사전 필터 | <1ms | <1ms | <1ms | Python set lookup |
| LLM (Sonnet) | — | ~400ms | ~400ms | ~500 token in, ~200 token out |
| BGE-M3 embed | ~15ms | ~15ms | ~30ms | DECOMPOSE: 2개 질의 임베딩 |
| Qdrant D+S RRF | ~20ms | ~20ms | ~40ms | DECOMPOSE: 2회 검색 |
| RRF merge | — | — | <1ms | Python in-memory |
| **합계** | **~35ms** | **~435ms** | **~470ms** | |

**참고**: 현재 Setting C의 p95 레이턴시는 48ms이다. REWRITE/DECOMPOSE에서 추가되는 ~400ms는 LLM 호출 시간이다. 이는 후단에서 LLM으로 답변을 생성하는 시간(1~3초)에 비하면 허용 가능한 수준이다.

### 4-2. 비용 분석

| 항목 | 값 | 산출 |
|------|---|------|
| LLM 호출당 입력 토큰 | ~500 | 시스템 프롬프트(~400) + 사용자 질의(~100) |
| LLM 호출당 출력 토큰 | ~200 | JSON 응답 |
| 호출당 비용 (Sonnet) | ~$0.0045 | Input $3/MTok × 0.5K + Output $15/MTok × 0.2K |
| 평균 비용/질의 (60% 호출) | ~$0.0027 | 0.6 × $0.0045 |
| **일 1,000 질의 기준** | **$2.70/일** | |
| **월간 비용** | **~$81/월** | |
| Prompt caching 적용 시 | **~$50/월** | 시스템 프롬프트 90% 할인 |

> **Prompt Caching이란?**
>
> Anthropic API의 기능으로, 동일한 시스템 프롬프트를 반복 전송할 때 첫 번째 요청에서 캐시하고 이후 요청에서는 캐시된 토큰을 재사용한다. 캐시된 입력 토큰은 90% 할인된 가격으로 과금된다. 우리의 시스템 프롬프트(~400 토큰)는 모든 호출에서 동일하므로 이 기능의 혜택이 크다.

### 4-3. Contextual Retrieval(P0-a)과의 비용 비교

| 항목 | P0-a (Contextual Retrieval) | P1-a (Query Decomposition) |
|------|---------------------------|---------------------------|
| 유형 | 일회성 배치 | 실시간 질의 시 |
| 총 비용 | ~$0.5 (180 배치) | ~$50~81/월 |
| 모델 | Sonnet | Sonnet |
| 호출 시점 | 인덱싱 전 (offline) | 검색 시 (online) |

---

## 5. 파일 구조 및 생성 파일

### 5-1. 신규 생성 파일 (6개)

```
codes/query/                             # 신규 디렉토리
    ├── __init__.py                      # 패키지 초기화
    ├── config.py                        # 상수, 모델명, 도메인 키워드 맵
    ├── prompts.py                       # 시스템/유저 프롬프트 템플릿
    ├── analyzer.py                      # QueryAnalyzer 클래스 (게이팅 + LLM 호출)
    ├── merger.py                        # rrf_merge() 결과 병합 함수
    ├── pipeline.py                      # SearchPipeline 오케스트레이터
    └── test_query_decomposition.py      # 평가 하니스 (벤치마크 스크립트)
```

### 5-2. 기존 파일 — 수정 없음 (재사용만)

| 파일 | 역할 | 재사용 방식 |
|------|------|-----------|
| `codes/embedding/embedder_bgem3.py` | `embed_query()` | import하여 서브 질의별 임베딩 |
| `codes/embedding/search_test_phase2_v2.py` | `search_ontology()`, `search_legal()`, `expected` dict | import하여 검색 + 평가 기준 재사용 |
| `codes/embedding/reranker.py` | `rerank_results()` | P1-b에서 결합 예정 (현 단계에서는 선택적) |
| `ontology_data/taxonomy.json` | 10개 도메인 브랜치 정의 | 프롬프트에 도메인 목록 포함 |
| `ontology_data/entries/*.json` | term + aliases (~21,000개) | 사전 필터용 set 로딩 |

### 5-3. 기존 API 패턴 재사용

Claude API 호출 패턴은 기존 코드(`scripts/build_ontology.py` 224~299행)를 따른다:

```python
# 기존 패턴 (build_ontology.py):
response = client.messages.create(
    model=MODEL,
    max_tokens=4096,
    system=SYSTEM_PROMPT,
    messages=[{"role": "user", "content": prompt}],
)
raw = response.content[0].text.strip()
# JSON 파싱 + 3회 재시도 + Rate Limit 대기
```

---

## 6. 구현 단계 및 일정

| Phase | 작업 | 산출물 | 소요 |
|-------|------|--------|------|
| **1** | 프롬프트 설계 + Analyzer 구현 | `prompts.py`, `config.py`, `analyzer.py` | 1일 |
| **2** | 파이프라인 통합 | `merger.py`, `pipeline.py` | 1일 |
| **3** | 평가 프레임워크 + 벤치마크 | `test_query_decomposition.py`, 결과 리포트 | 1~2일 |
| **4** | 최적화 + 문서화 | 사전 필터 튜닝, prompt caching, 최종 리포트 | 1일 |

### 성공 기준

| 지표 | 기준 | 의미 |
|------|------|------|
| 기존 25개 P@3 | ≥ 92% | 회귀 없음 |
| 실패 질의 2개 | 100% (2/2) 해결 | 핵심 목표 |
| Cross-domain 10개 | ≥ 80% | 신규 질의 커버리지 |
| LLM 호출율 | ≤ 60% | 비용/레이턴시 억제 |
| E2E Latency p95 | < 800ms | 서비스 수준 유지 |

---

## 7. 향후 연결

### P1-b: Cross-Encoder 재도입

Query Rewriting으로 후보 품질이 개선된 후, 기존 `reranker.py`의 Cross-Encoder를 2차 리랭커로 결합:

```
[현재 — P1-a 단독]
Query → LLM Analyzer → Embed → Qdrant D+S RRF → Top-K

[P1-b 추가 시]
Query → LLM Analyzer → Embed → Qdrant D+S RRF → Top-50
                                                    ↓
                                        Cross-Encoder rerank → Top-K
```

Setting E에서 "집 살 때 세금"→"취득세" Top-1(0.9346)을 달성한 Cross-Encoder의 **정밀 매칭 능력**이, Query Rewriting으로 개선된 후보 풀에서 더 효과적으로 작동할 것으로 기대.

---

## 8. 참고 문헌

| 분야 | 자료 | 출처 |
|------|------|------|
| Query Decomposition | TIDE (ACL 2025) | https://arxiv.org/abs/2507.00355 |
| Adaptive Classification | Adaptive-RAG (KAIST, 2024) | https://arxiv.org/html/2403.14403v2 |
| Confidence Gating | PruneRAG (2026) | https://arxiv.org/html/2601.11024 |
| Small-model Decomposition | Collab-RAG (2025) | https://arxiv.org/abs/2504.04915 |
| Multi-Agent RAG | MA-RAG (2025) | https://arxiv.org/abs/2505.20096 |
| Domain-Specific QA | DO-RAG (Tsinghua, 2025) | https://arxiv.org/html/2505.17058v1 |
| ⚠️ Fusion Scaling Limits | Scaling RAG Fusion (2026.03) | https://arxiv.org/abs/2603.02153 |
| Hop-wise Decomposition | DecomposeRAG | 논문 |
| Multi-Query Retrieval | LangChain MultiQueryRetriever | https://docs.langchain.com |
| Sub-Question Engine | LlamaIndex SubQuestionQueryEngine | https://docs.llamaindex.ai |
| Cross-Encoder Reranker | bge-reranker-v2-m3-ko | https://huggingface.co/dragonkue |
| MultiHop-RAG Benchmark | MultiHop-RAG | https://openreview.net/forum?id=t4eB3zYWBK |
