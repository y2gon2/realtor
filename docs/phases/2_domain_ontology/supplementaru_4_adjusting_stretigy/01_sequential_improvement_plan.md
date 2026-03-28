# P1-a/b 순차 보완 및 확장 벤치마크 계획

> 작성일: 2026-03-28 (500개 질의 확장 Baseline 실측 반영)
> 선행 문서: `05_benchmark_results.md` (500개 질의 Baseline), `10_expanded_benchmark_results.md` (C/E/F 비교)
> 목적: 500개 질의 Baseline 실측 결과를 기반으로 P1-a 보완 계획을 수립하고 5단계 순차 실행
> 테스트 질의: `data/test_question_v0.md` (500개, 5세트)
> 테스트 코드: `codes/query/test_queries.py` (단일 소스)
> 제외: P1-a-5 (API 직접 호출 전환) — 추후 제품 서비스 단계 반영

---

## 0. 배경 및 동기

### 0-1. 500개 질의 Baseline 실측 결과 (Setting C: Dense+Sparse RRF)

> 테스트 일시: 2026-03-28, 환경: DGX Spark, BGE-M3 + Qdrant v1.17.0

| 세트 | 질의 수 | 성격 | Baseline P@3 | 정답/총 | Avg Top-1 | p95 |
|------|--------|------|-------------|---------|----------|-----|
| **A (정규 질의)** | 150 | 전문/반전문 용어 포함 | **79.3%** | 119/150 | 0.8294 | 61ms |
| **B (극단 구어체)** | 50 | 전문용어 없는 순수 구어체 | **46.0%** | 23/50 | 0.7096 | 62ms |
| **C (Cross-Domain)** | 100 | 2+ 도메인 교차, 정규 용어 포함 | **81.0%** | 81/100 | 0.7942 | 62ms |
| **D (극단 구어체)** | 100 | 속어/비격식/감정 표현 | **50.0%** | 50/100 | 0.7270 | 64ms |
| **E (리서치 기반)** | 100 | 인터넷 속어/시사/3+ 도메인 | **56.0%** | 56/100 | 0.7824 | 65ms |
| **전체** | **500** | — | **65.8%** | **329/500** | **0.7885** | **65ms** |

### 0-2. 검색 설정(Setting) 비교 — 500개 질의 실측

| 설정 | 벡터 구성 | P@3 | Latency p95 | 판정 |
|------|----------|-----|------------|------|
| **C: D+S RRF** | Dense + Sparse | **65.8%** | **65ms** | **현행 최적 — 유지** |
| E: D+S RRF + CE | Dense + Sparse + Cross-Encoder | 62.6% (-3.2%p) | 146ms | 회귀 발생 |
| F: 3-Way RRF | Dense + Sparse + ColBERT | 65.4% (-0.4%p) | 221ms | 동등, 레이턴시 증가 |

### 0-3. 이전 42개 결과와의 비교

| 지표 | 구 42개 | 신 500개 | 변화 | 원인 |
|------|--------|---------|------|------|
| Set A P@3 | 92% (23/25) | 79.3% (119/150) | -12.7%p | 신규 A26~A150에 난이도 높은 질의 포함 |
| Set B P@3 | 50% (1/2) | 46.0% (23/50) | -4%p | 극단 구어체 48개 추가 |
| Set C P@3 | 90% (9/10) | 81.0% (81/100) | -9%p | Cross-domain 90개 추가 |
| Set D P@3 | 80% (4/5) | 50.0% (50/100) | -30%p | 극단 구어체 95개 추가 |
| 전체 P@3 | 88% (37/42) | 65.8% (329/500) | -22.2%p | **예상대로** — 극단 질의 확장 |

### 0-4. 핵심 발견 — 실측 데이터 기반

```
질의 유형별 P@3 분포 (500개 실측):

  Cross-Domain (Set C):   ████████████████████████████████████████░░░░░░░░  81.0%
  정규 질의 (Set A):       ██████████████████████████████████████░░░░░░░░░░  79.3%
  혼합형 (Set E):          ████████████████████████████░░░░░░░░░░░░░░░░░░░  56.0%
  극단 구어체 (Set D):      █████████████████████████░░░░░░░░░░░░░░░░░░░░░░  50.0%
  극단 구어체 (Set B):      ███████████████████████░░░░░░░░░░░░░░░░░░░░░░░░  46.0%
                          ─────────────────────────────────────────────────
                          0%        25%        50%        65.8%  75%   100%
```

**핵심 결론:**

1. **정규 용어가 있으면 벡터 검색이 작동** (Set A+C: 평균 80%)
2. **구어체 질의는 벡터 검색만으로 해결 불가** (Set B+D: 평균 48%)
3. **인터넷 속어/시사 이슈는 중간** (Set E: 56%) — 일부 정규 용어 포함
4. **Cross-Encoder(Setting E)는 오히려 회귀** — CE 점수 양극화 문제
5. **ColBERT(Setting F)는 레이턴시만 증가** — P@3 동등

### 0-5. 핵심 문제와 해결 단계

> **쉬운 비유 — 병원 진료:**
>
> 1. **과잉 진료 (Over-rewriting)**: 감기 환자에게 MRI를 찍는 것처럼, 이미 잘 매칭되는 질의를 불필요하게 변환
> 2. **오진 (DECOMPOSE 실패)**: "머리 아프고 열 나요"를 "두통과 발열"로 분리 진료하다가, 핵심 원인(독감)을 놓치는 것
> 3. **불필요한 의뢰 (LLM 과다 호출)**: 약국에서 해결 가능한 환자를 전문의에게 보내는 비효율
> 4. **언어 장벽 (어휘 격차)**: "나라에 돈 내야 되나" → "취득세" 변환이 필요한데 통역사(LLM) 없이는 불가능

| 문제 | 실측 증거 | 원인 | 해결 단계 |
|------|---------|------|----------|
| 구어체 검색 실패 | Set B 46%, Set D 50% | 어휘 격차 → Dense/Sparse 모두 실패 | **Step 1: 하이브리드 전략** + LLM REWRITE |
| DECOMPOSE 유해 | 구 42개 기준 개선 0건, 회귀 5건 | 단일 주제를 잘못 분해 | **Step 2: DECOMPOSE 보수화** |
| LLM 과다 호출 | 구 42개 기준 88% (목표 60%) | 사전 필터 미작동 | **Step 3: 사전 필터 정교화** |
| REWRITE 키워드 소실 | 구 42개 기준 2건 회귀 | 프롬프트 미지시 | **Step 4: 프롬프트 보수성** |
| CE 회귀 | Setting E: -3.2%p (62.6%) | CE 점수 양극화, 순위 뒤집힘 | **Step 5: 점수 퓨전 Cross-Encoder** |

---

## 1. 테스트 질의 확장 (42 → 500개)

### 1-1. 확장 규모

| 세트 | 구 (42개) | 최종 (500개) | 성격 |
|------|---------|------------|------|
| A (회귀) | 25 | **150** | 정형/반구어체, 도메인 균형, 10개 도메인 고르게 배분 |
| B (극단 실패) | 2 | **50** | 전문용어 없는 순수 구어체, 의미 격차 극대 |
| C (Cross-Domain) | 10 | **100** | 2+ 도메인 교차, 45개 도메인 쌍 커버 |
| D (극단 구어체) | 5 | **100** | 속어/비격식/감정 표현, 10개 도메인 × 10개 |
| E (리서치 기반) | — | **100** | 인터넷 속어("영끌","깡통","줍줍","부린이"), 3+ 도메인, 2024-2026 시사, 커뮤니티 패턴 |

### 1-2. 질의 설계 원칙

> RAG 평가 질의 설계에 관한 최근 연구 (Asai et al., 2024; Chen et al., 2025)에 따르면:
>
> 1. **도메인 균형**: 10개 도메인 모두에서 최소 8개 이상의 질의로 편향 방지
> 2. **난이도 층화 (Difficulty Stratification)**: SIMPLE(정규 용어) → REWRITE(구어체) → DECOMPOSE(복합) 고르게
> 3. **질문 유형 10가지**: 세금/비용, 절차, 자격, 개념, 규제, 비교, 법적분쟁, 서류, 투자, 감정
> 4. **기대 결과 명확화**: 각 질의에 P@3 평가용 기대 키워드 3~5개 사전 정의

### 1-3. 구현 파일

| 파일 | 역할 |
|------|------|
| `data/test_question_v0.md` | 500개 질의 정의 문서 (5세트, 기대 키워드, 도메인 태그) |
| `codes/query/test_queries.py` | Python 단일 소스 (SET_A~E_QUERIES, EXPECTED_KEYWORDS) |
| `codes/query/test_query_decomposition.py` | 벤치마크 하니스 (5세트, baseline/full/full_rerank) |
| `data/test_question_research_sources.md` | 리서치 소스 (240개, 출처별 패턴) |
| `data/cross_domain_questions_research.md` | Cross-domain 리서치 (100개, 도메인 교차 패턴) |

---

## 2. Step 1 — P1-a-1: 하이브리드 전략 (원본 + 변환 동시 검색)

### 2-1. 핵심 아이디어

> **쉬운 비유 — 통역사와 원본 동시 제출:**
>
> 외국어 서류를 관공서에 제출할 때, **번역본만** 내면 번역 오류 시 처리가 잘못될 수 있다.
> **원본 + 번역본을 함께** 제출하면, 번역이 틀려도 원본이 보험 역할을 한다.

**현재 흐름:**
```
Query → LLM 변환 → 변환된 질의만 검색 → 결과
```

**개선 흐름:**
```
Query → LLM 변환 → 변환된 질의 검색 ─┐
  │                                    ├→ RRF 합산 → Top-K
  └──────────→ 원본 질의도 검색 ───────┘
```

### 2-2. 이론적 근거

> **RRF (Reciprocal Rank Fusion)란?**
>
> 여러 검색 결과 목록을 하나로 합치는 알고리즘이다.
> 쉬운 비유: 여러 심사위원이 각각 후보에게 순위를 매긴 후, **"순위가 높을수록 점수를 많이 주는"** 방식으로 종합 순위를 계산한다.
>
> 수식: `RRF_score(doc) = Σ weight_i × 1/(k + rank_i + 1)` (k=60, 원 논문 권장값)

관련 연구:
- **RAG-Fusion** (Raudaschl, 2023): 원본 + N개 변형 질의를 모두 검색 후 RRF 합산.
- **HyDE + Original Blend** (Wang et al., 2023): Hypothetical Document만 검색 시 hallucination 리스크 → 원본 병행 권장.
- **Scaling RAG Fusion** (2026.03): re-ranking 하에서 RAG Fusion 효과 소멸 경고 → **가중치 설계가 핵심**.

### 2-3. RRF 가중치 설계

> **쉬운 비유 — 위원회 투표:**
>
> 원본 질의 = **선임 위원** (가중치 높음): 이미 검증된 결과
> 변환 질의 = **신임 위원** (가중치 낮음): 새로운 관점 제공

| 분석 유형 | 원본 가중치 | 변환 가중치 | 근거 |
|----------|-----------|-----------|------|
| SIMPLE | 1.0 (단독) | — | 변환 없음, 원본만 사용 |
| REWRITE | 1.0 | 0.8 | 정규 질의 79.3% 성공 → 원본 보존 우선 |
| DECOMPOSE | 1.2 | 0.6 (각 서브) | 구 벤치마크에서 회귀 5건 → 원본 가중치 강화 |

### 2-4. 수정 파일 (구현 완료)

| 파일 | 변경 내용 |
|------|---------|
| `codes/query/config.py` | 가중치 상수 4개: `ORIGINAL_WEIGHT_REWRITE=1.0`, `TRANSFORMED_WEIGHT_REWRITE=0.8`, `ORIGINAL_WEIGHT_DECOMPOSE=1.2`, `SUB_QUERY_WEIGHT_DECOMPOSE=0.6` |
| `codes/query/pipeline.py` | `search()` 리팩토링 — 원본 항상 검색 + `_compute_weights()` 헬퍼 |

### 2-5. 기대 효과 (500개 질의 기준)

| 세트 | Baseline P@3 | 예상 Full P@3 | 근거 |
|------|-------------|-------------|------|
| A (150) | 79.3% | **≥ 79.3%** | 원본 항상 포함 → 회귀 불가 |
| B (50) | 46.0% | **≥ 60%** | REWRITE로 구어체 변환 + 원본 보존 |
| C (100) | 81.0% | **≥ 81%** | 원본 보존으로 DECOMPOSE 회귀 방지 |
| D (100) | 50.0% | **≥ 55%** | REWRITE 효과 + 원본 보존 |
| E (100) | 56.0% | **≥ 58%** | 인터넷 속어 → 전문용어 변환 기대 |

### 2-6. 벤치마크

```bash
python3 codes/query/test_query_decomposition.py --set all --output results/p1a_step1_hybrid.json
```

**성공 기준:** 전체 P@3 ≥ 65.8% (Baseline 이상), 회귀 0건

---

## 3. Step 2 — P1-a-3: DECOMPOSE 보수적 적용

### 3-1. 문제 요약

구 42개 벤치마크에서 DECOMPOSE는 **개선 0건, 회귀 5건**이다.

> **쉬운 비유 — 주문 분리:**
>
> 식당에서 "스테이크에 와인 페어링 추천해줘"라고 주문하면:
> - **REWRITE** (좋음): "스테이크와 어울리는 레드 와인" — 하나의 질의로 처리
> - **DECOMPOSE** (나쁨): ① "스테이크 추천" ② "와인 추천" — 분리하면 **페어링이라는 핵심 맥락이 사라짐**

### 3-2. 3단계 방어 전략 (구현 완료)

**방어 1 — 프롬프트 보수화** (`prompts.py`):
- DECOMPOSE 예시 → REWRITE로 변경
- "완전히 독립적인 주제"에만 DECOMPOSE 허용
- 각 서브 질의에 원본 키워드 필수 포함

**방어 2 — 단일 도메인 DECOMPOSE→REWRITE 자동 변환** (`analyzer.py`):
```python
if qtype == "DECOMPOSE" and len(sub_queries) > 1:
    domains = set(sq.domain_hint for sq in sub_queries)
    if len(domains) == 1:
        qtype = "REWRITE"
        sub_queries = [sub_queries[0]]
```

**방어 3 — Step 1의 하이브리드 전략이 최종 안전망**

### 3-3. 벤치마크

```bash
python3 codes/query/test_query_decomposition.py --set all --output results/p1a_step2_decompose.json
```

**성공 기준:** DECOMPOSE 회귀 0건, DECOMPOSE 발생 빈도 ≤ 10%

---

## 4. Step 3 — P1-a-2: 사전 필터 정교화

### 4-1. 현황

> **쉬운 비유 — 공항 보안 검색:**
>
> 현재: "가방 크기 15cm 이하"만 통과 → 대부분 정밀 검색(LLM) 대상
> 개선: 기준 완화(25cm) + VIP 패스(전문용어 2개+) → LLM 호출 절반 감소

### 4-2. 변경 사항 (구현 완료)

| 변경 | 내용 | 파일 |
|------|------|------|
| `MAX_SIMPLE_LENGTH` | 15 → **25** | `config.py` |
| 정규 용어 확장 | entries + taxonomy.json + 약어 사전 | `analyzer.py` |
| 도메인 키워드 | 10개 도메인 × 10~14개 키워드 | `config.py` |
| 다중 요소 판정 | 용어 수 + 도메인 수 + 인과패턴 + 구어체 점수 | `analyzer.py` |
| 구어체 점수 | `COLLOQUIAL_MARKERS` 13개 마커 카운팅 | `analyzer.py` |

### 4-3. 기대 효과

| 지표 | 구 42개 기준 | 500개 예상 |
|------|------------|----------|
| SIMPLE 판정율 | 12% (5/42) | **25-35%** |
| LLM 호출율 | 88% | **50-60%** |

### 4-4. 벤치마크

```bash
python3 codes/query/test_query_decomposition.py --set all --output results/p1a_step3_prefilter.json
```

**성공 기준:** LLM 호출율 ≤ 60%, Set A P@3 ≥ 79.3%, 구어체 SIMPLE 오판 0건

---

## 5. Step 4 — P1-a-4: 프롬프트 보수성 강화

### 5-1. 변경 사항 (구현 완료)

| 변경 | 내용 | 파일 |
|------|------|------|
| 보수적 원칙 | SIMPLE 우선, REWRITE 최소 변환, DECOMPOSE 극히 제한 | `prompts.py` |
| 사전 분석 컨텍스트 | User Prompt에 감지된 용어/도메인/인과패턴 전달 | `prompts.py` + `analyzer.py` |
| REWRITE 후처리 | `_validate_rewrite()` — 원본 키워드 소실 시 보충 | `analyzer.py` |

### 5-2. 벤치마크

```bash
python3 codes/query/test_query_decomposition.py --set all --output results/p1a_step4_prompt.json
```

**성공 기준:** REWRITE 회귀 0건, Set B P@3 ≥ 60%, Set E P@3 ≥ 58%

---

## 6. Step 5 — P1-b: Cross-Encoder 재도입 (점수 퓨전)

### 6-1. 이전 실패 분석 — 500개 실측

Setting E (CE 단독 교체) 실측:
- **전체 P@3**: 65.8% → **62.6%** (-3.2%p 회귀)
- **Set B**: 46.0% → **38.0%** (-8%p, 최악 회귀)
- **원인**: CE 점수 양극화 (대부분 0 또는 1), RRF의 "다양성 투표" 장점 상실

### 6-2. 새 전략: 점수 퓨전

> **쉬운 비유 — 1차 서류심사 + 2차 면접:**
>
> **이전 (실패)**: 면접관(CE) 판단으로 서류심사(RRF) 결과를 전부 교체
> **새 방식**: 서류심사 점수 + 면접 점수를 **종합**하여 최종 결정

```
final_score = α × normalized_rrf_rank + (1 - α) × ce_score
```

> **Cross-Encoder (CE)란?**
>
> 일반 검색(Bi-Encoder)은 질의와 문서를 각각 벡터로 만들어 거리를 비교한다.
> Cross-Encoder는 질의-문서 쌍을 **하나의 입력으로 합쳐서** 모델이 직접 관련도를 판단한다.
> 더 정확하지만, 모든 후보에 대해 개별 추론이 필요해 느리다 (후보 20개 → 20번 추론).

### 6-3. 수정 파일 (구현 완료)

| 파일 | 변경 |
|------|------|
| `codes/query/pipeline.py` | `rerank` 파라미터 + `_rerank_ontology()` (CE 호출 + 점수 퓨전) |
| `codes/query/test_query_decomposition.py` | `full_rerank` 설정, `--setting full_rerank` 옵션 |

### 6-4. 벤치마크

```bash
# Full Pipeline + CE Rerank
python3 codes/query/test_query_decomposition.py --set all --setting full_rerank \
    --output results/p1b_step5_rerank.json

# α 그리드 서치 (선택)
# codes/query/tune_rerank_alpha.py 작성 후 실행
```

**성공 기준:** 전체 P@3 ≥ 65.8% (Baseline 이상), Avg Top-1 ≥ +2%

### 6-5. 폴백 계획

α 전범위에서 개선 없으면:
1. REWRITE 질의에만 CE 적용 (SIMPLE bypass)
2. Top-3은 RRF 유지, 4-20위만 CE 리랭킹
3. CE 없이 Step 1-4 결과만으로 운영

---

## 7. 전체 실행 순서 및 산출물

| 순서 | 작업 | 수정 파일 | 상태 | 벤치마크 산출물 |
|------|------|---------|------|--------------|
| **Step 0** | 테스트 확장 42→500 | `test_queries.py`, `test_query_decomposition.py` | **완료** | `p1a_benchmark_v4_baseline.json` |
| **Step 1** | 하이브리드 전략 | `pipeline.py`, `config.py` | **구현 완료** | `p1a_step1_hybrid.json` |
| **Step 2** | DECOMPOSE 보수화 | `prompts.py`, `analyzer.py` | **구현 완료** | `p1a_step2_decompose.json` |
| **Step 3** | 사전 필터 정교화 | `config.py`, `analyzer.py` | **구현 완료** | `p1a_step3_prefilter.json` |
| **Step 4** | 프롬프트 보수성 | `prompts.py`, `analyzer.py` | **구현 완료** | `p1a_step4_prompt.json` |
| **Step 5** | Cross-Encoder 퓨전 | `pipeline.py`, `reranker.py` | **구현 완료** | `p1b_step5_rerank.json` |

> **상태**: Step 0 Baseline 실측 완료. Step 1~5 코드 구현 완료. Full LLM Pipeline 벤치마크 실행 대기 (~42분 소요 예상).

### 결과 문서

```
planning/docs/phases/2_domain_ontology/supplementary_3_cross_domain/
  05_benchmark_results.md           ← 500개 Baseline 실측 결과
  06_sequential_improvement_plan.md ← 본 문서 (계획 + 구현 상태)
  07_step1_hybrid_results.md        ← Step 1 실행 후 작성
  08_step2_decompose_results.md
  09_step3_prefilter_results.md
  10_step4_prompt_results.md
  11_step5_cross_encoder_results.md
```

---

## 8. 검증 계획

### 8-1. 각 단계 공통 검증 항목

1. **P@3 비교표**: Baseline vs Full (5세트 × 2설정)
2. **회귀 분석**: 이전 단계 대비 신규 회귀 건수 (0건 목표)
3. **LLM 호출율**: Step 3 이후 ≤ 60% 확인
4. **유형별 분포**: SIMPLE/REWRITE/DECOMPOSE 비율 변화 추적
5. **레이턴시**: p95 변화 추적
6. **Avg Top-1**: 의미적 매칭 품질 추적

### 8-2. 최종 목표 (Step 5 완료 후)

| 지표 | Baseline (실측) | 최종 목표 | 개선 목표 |
|------|---------------|---------|---------|
| Set A P@3 | 79.3% | ≥ 85% | +5.7%p |
| Set B P@3 | 46.0% | ≥ 65% | +19%p |
| Set C P@3 | 81.0% | ≥ 85% | +4%p |
| Set D P@3 | 50.0% | ≥ 60% | +10%p |
| Set E P@3 | 56.0% | ≥ 65% | +9%p |
| **전체 P@3** | **65.8%** | **≥ 75%** | **+9.2%p** |
| LLM 호출율 | — | ≤ 55% | — |
| 회귀 건수 | — | 0건 | — |

---

## 9. 성과 궤적

```
Phase 2 검색 성능 개선 궤적 (온톨로지):

Precision@3:
  Phase 2 초기 (25개):         80%
  + Contextual Retrieval:      90%   (+10%p)
  + BGE-M3 D+S RRF:           92%   (+2%p)   ← 구 운영 기준

500개 확장 후 재측정:
  Baseline (Setting C):        65.8%           ← 현재 (구어체 포함)
  + Cross-Encoder (Setting E): 62.6%  (-3.2%p) ← 미채택
  + 3-Way RRF (Setting F):    65.4%  (-0.4%p) ← 미채택

목표 (P1-a/b 순차 보완 후):
  + Step 1-4 (Query Rewriting): ~73%   (예상)
  + Step 5 (CE 점수 퓨전):     ≥75%   (목표)
```

---

## 10. 위험 요소 및 대응

| 위험 | 확률 | 영향 | 대응 |
|------|------|------|------|
| LLM 호출 비용/시간 | 높음 | 높음 | 사전 필터로 호출율 ≤ 55%로 억제. API 전환(P1-a-5)은 추후 |
| 하이브리드 가중치 최적값 미달 | 낮음 | 중간 | `config.py` 상수 튜닝으로 즉시 조정 가능 |
| 500개 질의 기대 키워드 오류 | 중간 | 높음 | 온톨로지 대조 검증. 오판 발견 시 `test_queries.py` 즉시 수정 |
| CE 점수 퓨전이 P@3 개선 미달 | 중간 | 낮음 | CE 없이 Step 1-4만으로 운영 가능 (폴백) |
| 인터넷 속어 질의(Set E) 지속 실패 | 높음 | 중간 | 온톨로지에 속어 alias 추가 또는 별도 속어 사전 구축 |
| LLM 프롬프트 변경 후 예측 불가 동작 | 중간 | 중간 | Step별 순차 적용 + 벤치마크로 즉시 감지 |
