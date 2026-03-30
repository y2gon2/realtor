# P1-a/b 순차 보완 — 실행 프레임워크

> 작성일: 2026-03-28
> 선행 문서: `01_sequential_improvement_plan.md`
> 목적: 5단계 순차 개선의 공통 실행 프레임워크, 의존 관계, 검증 체계, 위험 관리 정의
> 테스트 질의: `data/test_question_v0.md` (500개, 5세트)
> 테스트 코드: `codes/query/test_query_decomposition.py`

---

## 0. 현황 요약

### 0-1. 성능 기준선 (500개 질의, Setting C: Dense+Sparse RRF)

| 세트 | 질의 수 | P@3 | Avg Top-1 | p95 | 성격 |
|------|--------|-----|----------|-----|------|
| A (정규) | 150 | 79.3% | 0.8294 | 61ms | 전문/반전문 용어 |
| B (극단 구어체) | 50 | 46.0% | 0.7096 | 62ms | 전문용어 부재 |
| C (Cross-Domain) | 100 | 81.0% | 0.7942 | 62ms | 2+ 도메인 교차 |
| D (극단 구어체) | 100 | 50.0% | 0.7270 | 64ms | 속어/비격식 |
| E (혼합형) | 100 | 56.0% | 0.7824 | 65ms | 인터넷 속어+시사 |
| **전체** | **500** | **65.8%** | **0.7885** | **65ms** | — |

### 0-2. 핵심 병목

```
정규+Cross-Domain (A+C, 250개):  ████████████████████████████████████████░░░░░░░░  80.0%
구어체+슬랭 (B+D+E, 250개):      █████████████████████████░░░░░░░░░░░░░░░░░░░░░░  51.6%
                                  ─────────────────────────────────────────────────
                                  0%        25%        50%        65.8%  75%   100%

→ 전체 질의의 50%가 구어체/슬랭이며, 이 구간에서 절반 이상 실패
→ 검색 설정(C/E/F) 변경으로는 해결 불가 → LLM Query Rewriting 필수
```

### 0-3. 42개 질의 레거시 교훈

| 유형 | 호출 수 | 개선 | 회귀 | 순효과 | 교훈 |
|------|--------|------|------|--------|------|
| SIMPLE | 5 | 0 | 0 | 중립 | 안전 — 확대 필요 |
| REWRITE | 20 | +2 | -2 | 0 | Set B 핵심 해결이지만 과잉 변환 문제 |
| DECOMPOSE | 12 | 0 | -5 | -5 | **회귀 주범** — 근본적 재설계 필요 |

### 0-4. 실행 원칙

1. **순차 적용 + 단계별 검증**: 각 Step 완료 후 500개 벤치마크로 회귀 확인
2. **Baseline 보호**: 정규 질의(A+C) P@3 ≥ 80% 유지가 최우선
3. **단일 변수 변경**: 한 번에 하나만 변경하여 효과를 정확히 측정
4. **폴백 보장**: 각 Step이 실패해도 이전 단계로 즉시 롤백 가능

---

## 1. 단계별 문서 구조

| 문서 | 파일명 | 핵심 내용 | 수정 파일 |
|------|--------|---------|----------|
| 본 문서 | `02_execution_overview.md` | 공통 프레임워크 | — |
| Step 1 | `03_step1_hybrid_strategy.md` | 원본+변환 동시 검색, Weighted RRF | `pipeline.py`, `config.py`, `merger.py` |
| Step 2 | `04_step2_decompose_conservatism.md` | DECOMPOSE 3단계 방어 | `prompts.py`, `analyzer.py` |
| Step 3 | `05_step3_prefilter_refinement.md` | 사전 필터 정교화, LLM 호출율 감소 | `config.py`, `analyzer.py` |
| Step 4 | `06_step4_prompt_conservatism.md` | 프롬프트 보수성, 키워드 보존 | `prompts.py`, `analyzer.py` |
| Step 5 | `07_step5_cross_encoder_fusion.md` | CE 점수 퓨전 재도입 | `pipeline.py` |

---

## 2. 실행 순서 및 의존 관계

### 2-1. 실행 순서도

```
Step 0 (완료)              Step 1                  Step 2
테스트 확장 42→500  ─────→  하이브리드 전략   ─────→  DECOMPOSE 보수화
  └ Baseline 실측           └ pipeline.py            └ prompts.py
    65.8% P@3               └ config.py              └ analyzer.py
                            └ 벤치마크 (~42min)       └ 벤치마크 (~42min)
                                  │                        │
                                  ▼                        ▼
                            Step 3                  Step 4
                     ─────→  사전 필터 정교화  ─────→  프롬프트 보수성
                            └ config.py              └ prompts.py
                            └ analyzer.py            └ analyzer.py
                            └ 벤치마크 (~42min)       └ 벤치마크 (~42min)
                                                           │
                                                           ▼
                                                     Step 5
                                                ─────→  CE 점수 퓨전
                                                     └ pipeline.py
                                                     └ 벤치마크 (~42min)
```

### 2-2. 의존 관계

| Step | 선행 의존 | 병렬 가능? |
|------|---------|----------|
| Step 1 | Step 0 (완료) | — |
| Step 2 | Step 1 (하이브리드가 안전망) | 코드는 병렬, 벤치마크는 순차 |
| Step 3 | Step 2 (DECOMPOSE 방어 완료 후 필터 조정) | 코드는 병렬, 벤치마크는 순차 |
| Step 4 | Step 3 (필터 확정 후 프롬프트 조정) | 코드는 병렬, 벤치마크는 순차 |
| Step 5 | Step 4 (모든 Query Rewriting 안정화 후 CE 재도입) | 코드는 병렬, 벤치마크는 순차 |

### 2-3. 총 소요 시간 추정

| 항목 | 시간 |
|------|------|
| Step 1~4 코드 구현 | **이미 완료** |
| Step 1~4 벤치마크 (각 ~42분) | ~2.8시간 |
| Step 5 벤치마크 + α 그리드 서치 (6α) | ~4.2시간 |
| 결과 분석 + 문서화 | ~2시간 |
| **총합** | **~6~10시간** (벤치마크는 자동 실행) |

---

## 3. 누적 목표 달성 추적표

### 3-1. 각 Step별 누적 목표

| 지표 | Baseline | Step 1 후 | Step 2 후 | Step 3 후 | Step 4 후 | Step 5 후 (최종) |
|------|---------|----------|----------|----------|----------|---------------|
| Set A P@3 | 79.3% | ≥ 79.3% | ≥ 79.3% | ≥ 79.3% | ≥ 80% | **≥ 85%** |
| Set B P@3 | 46.0% | ≥ 50% | ≥ 50% | ≥ 50% | ≥ 60% | **≥ 65%** |
| Set C P@3 | 81.0% | ≥ 81% | ≥ 81% | ≥ 81% | ≥ 82% | **≥ 85%** |
| Set D P@3 | 50.0% | ≥ 52% | ≥ 52% | ≥ 52% | ≥ 55% | **≥ 60%** |
| Set E P@3 | 56.0% | ≥ 56% | ≥ 56% | ≥ 56% | ≥ 58% | **≥ 65%** |
| **전체** | **65.8%** | **≥ 66%** | **≥ 67%** | **≥ 68%** | **≥ 71%** | **≥ 75%** |
| LLM 호출율 | — | — | — | ≤ 60% | ≤ 55% | ≤ 55% |
| 회귀 건수 | — | 0 | 0 | 0 | 0 | 0 |
| Latency p95 | 65ms | ≤ 130ms | ≤ 130ms | ≤ 130ms | ≤ 130ms | ≤ 250ms |

### 3-2. 성과 궤적 (예상)

```
Phase 2 검색 성능 궤적:

── 이전 ──
  초기:                              80%
  + Contextual Retrieval:            90%   (+10%p)
  + BGE-M3 D+S RRF:                92%   (+2%p)

── 500개 확장 ──
  Baseline (Setting C):              65.8%

── P1-a/b 순차 보완 (예상) ──
  + Step 1 (Hybrid):                ~67%   (+1.2%p) — 원본 보호
  + Step 2 (DECOMPOSE 보수):        ~68%   (+1%p) — 회귀 제거
  + Step 3 (사전 필터):              ~69%   (+1%p) — 오판 감소
  + Step 4 (프롬프트 보수):          ~73%   (+4%p) — 구어체 변환 효과
  + Step 5 (CE 점수 퓨전):          ≥75%   (+2%p) — 정밀 리랭킹
```

---

## 4. 검증 체계

### 4-1. 각 단계 공통 검증 항목

모든 Step에서 다음 6개 지표를 측정한다:

| # | 지표 | 측정 방법 | 기록 위치 |
|---|------|---------|----------|
| 1 | P@3 비교표 | Baseline vs Full, 5세트 × 2설정 | JSON `precision_at_3` |
| 2 | 회귀 분석 | 이전 단계 대비 신규 회귀 건수 | JSON `regressions` |
| 3 | LLM 호출율 | SIMPLE / REWRITE / DECOMPOSE 비율 | JSON `type_distribution` |
| 4 | 유형별 분포 | 3가지 유형의 비율 변화 추적 | JSON `type_counts` |
| 5 | 레이턴시 | p50, p95, p99 | JSON `latency` |
| 6 | Avg Top-1 | 의미적 매칭 품질 | JSON `avg_top1` |

### 4-2. 회귀 탐지 프로토콜

> **회귀(regression)**란?
>
> 이전에 정상 작동하던 기능이 코드 변경 후 오히려 나빠지는 현상이다. 검색 시스템에서는 "이전에 정답이 Top-3에 있었는데 변경 후 빠지는 것"을 회귀라 한다.

```python
def detect_regressions(baseline_results, full_results):
    """개별 질의 레벨에서 회귀 탐지.

    회귀 정의: Baseline에서 P@3=1 (정답 포함)이었으나
              Full에서 P@3=0 (정답 미포함)
    """
    regressions = []
    for query_id in baseline_results:
        baseline_ok = baseline_results[query_id]["precision_ok"]
        full_ok = full_results[query_id]["precision_ok"]
        if baseline_ok and not full_ok:
            regressions.append({
                "query": baseline_results[query_id]["query"],
                "analysis_type": full_results[query_id].get("analysis_type", "?"),
            })
    return regressions
```

### 4-3. 통계적 유의성 검정

> 500개 질의에서 2%p 미만의 차이는 통계적으로 유의하지 않을 수 있다. Wilcoxon signed-rank test로 검증한다.
>
> **Wilcoxon signed-rank test란?**
>
> 두 가지 처리(Baseline vs Full)의 결과를 **쌍으로 비교**하는 비모수 통계 검정이다. 각 질의에 대해 두 설정의 결과가 달라지는 정도를 순위화하여, 전체적으로 유의미한 차이가 있는지 판단한다.
>
> 참고: Smucker, Allan & Carterette, "A Comparison of Statistical Significance Tests for Information Retrieval Evaluation" (SIGIR 2007) — https://dl.acm.org/doi/10.1145/1277741.1277798

```python
from scipy import stats

def paired_significance_test(baseline_scores, full_scores, alpha=0.05):
    """두 설정 간 유의미한 차이 확인."""
    stat, p_value = stats.wilcoxon(baseline_scores, full_scores)
    return {
        "test": "Wilcoxon signed-rank",
        "p_value": p_value,
        "significant": p_value < alpha,
    }
```

### 4-4. 결과 문서 구조

각 Step 완료 후 결과 문서를 `results/` 디렉토리에 JSON으로 저장한다:

```
results/
  p1a_step1_hybrid.json
  p1a_step2_decompose.json
  p1a_step3_prefilter.json
  p1a_step4_prompt.json
  p1b_step5_rerank.json
```

---

## 5. 위험 관리

### 5-1. 위험 식별 및 대응

| # | 위험 | 확률 | 영향 | 대응 |
|---|------|------|------|------|
| R1 | LLM 호출 비용 초과 | 중 | 중 | Step 3에서 호출율 ≤ 55% 억제. Prompt caching ~$50/월 |
| R2 | 하이브리드 가중치 최적화 실패 | 낮 | 낮 | config.py 상수 즉시 조정. 16조합 그리드 서치 |
| R3 | 500개 질의 기대 키워드 오류 | 중 | 높 | 온톨로지 대조 검증. test_queries.py 즉시 수정 |
| R4 | CE 점수 퓨전 미개선 | 중 | 낮 | CE 없이 Step 1~4만 운영 (폴백 3) |
| R5 | 인터넷 속어(Set E) 지속 실패 | 높 | 중 | 온톨로지에 속어 alias 추가, 별도 매핑 사전 |
| R6 | LLM 프롬프트 비결정적 동작 | 중 | 중 | 단계별 벤치마크로 즉시 감지. temperature=0 고정 |
| R7 | 벤치마크 42분 소요 → 반복 병목 | 높 | 중 | Set A(150개)만 빠른 검증 → 통과 시 전체 실행 |
| R8 | YouTube 코퍼스 특수성 | 중 | 높 | 아래 §5-2 참조 |

### 5-2. R8 상세 — YouTube 스크립트 코퍼스 특수성

> **중요 발견**: 우리 코퍼스는 YouTube 스크립트이므로 **문서 자체가 구어체**를 포함한다. 일반적인 RAG와 달리 구어체 질의가 구어체 스크립트와 직접 매칭될 수 있다.

| 방향 | 시사점 | 대응 |
|------|--------|------|
| 긍정 | 구어체 질의가 스크립트와 직접 매칭 가능 | 원본 질의를 항상 보존 (Step 1) |
| 부정 | REWRITE로 전문용어화하면 스크립트 매칭이 약화 | 원본 + 변환 모두 검색 필수 |

→ **Step 1 하이브리드 전략이 핵심**

---

## 6. 참고 문헌 종합

### 6-1. 하이브리드 검색 전략

| 자료 | 핵심 기여 | Step |
|------|---------|------|
| RAG-Fusion (Raudaschl, 2023) | 원본+N개 변형 RRF 합산 | 1 |
| HyDE (Gao et al., ACL 2023) | 가설 문서 + 원본 병행 | 1 |
| Query2Doc (Wang et al., EMNLP 2023) | pseudo-document prepend | 1, 4 |
| RRF (Cormack et al., 2009) | k=60 최적, weighted 확장 | 1 |

### 6-2. 질의 분해

| 자료 | 핵심 기여 | Step |
|------|---------|------|
| Decomposed Prompting (Khot et al., ICLR 2023) | single-hop 분해 해로움 | 2 |
| Self-Ask (Press et al., ICLR 2023) | 분해 필요성 사전 판단 | 2 |
| DecomposeRAG | 1-hop +1.3%, 3-hop +82.2% | 2 |
| Adaptive-RAG (Jeong et al., NAACL 2024) | 3단계 라우팅 | 2, 3 |
| PruneRAG (Jiao et al., 2026) | 검색 호출 4.9× 감소 | 3 |

### 6-3. Cross-Encoder

| 자료 | 핵심 기여 | Step |
|------|---------|------|
| RankGPT (Sun et al., EMNLP 2023) | LLM listwise reranking | 5 |
| bge-reranker-v2-m3-ko (dragonkue) | 한국어 CE, F1 0.91 | 5 |
| Qwen3-Reranker-4B (instructkr 벤치마크) | MRR@10 0.83 (한국어 1위) | 5 |
| Score Injection (IR Journal, 2024) | BM25 점수를 CE 입력에 주입 | 5 |

### 6-4. 구어체/비정형 질의

| 자료 | 핵심 기여 | Step |
|------|---------|------|
| DMQR-RAG (Li et al., 2024) | 4가지 Rewriting 전략 | 4 |
| RaFe (Mao et al., EMNLP 2024 Findings) | Reranker feedback → Rewriter 학습 | 4 |
| Korean Tokenizer Benchmark (AutoRAG) | Okt/Mecab 한국어 BM25 비교 | 3, 4 |

### 6-5. 평가 방법론

| 자료 | 핵심 기여 |
|------|---------|
| RAGAS (Shahul Es et al., EACL 2024) | Faithfulness, Answer Relevancy 자동 메트릭 |
| 통계적 유의성 (Smucker et al., SIGIR 2007) | Paired bootstrap, Wilcoxon |
| RAGRouter-Bench (Wang et al., 2026) | No single RAG paradigm is universally optimal |
