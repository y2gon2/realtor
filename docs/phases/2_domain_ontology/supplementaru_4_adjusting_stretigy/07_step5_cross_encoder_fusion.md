# Step 5 — Cross-Encoder 점수 퓨전 재도입

> 작성일: 2026-03-28
> 선행 문서: `06_step4_prompt_conservatism.md`, `02_execution_overview.md`
> 목적: Cross-Encoder를 점수 퓨전 방식으로 재도입, 이전 실패(Setting E: -3.2%p) 원인 해결
> 수정 파일: `codes/query/pipeline.py`
> 상태: **구현 완료**, 벤치마크 실행 대기

---

## 0. 이전 실패 분석

### 0-1. Setting E 실측 결과 (500개 질의)

| 설정 | P@3 | Set B | Avg Top-1 | p95 | 판정 |
|------|-----|-------|----------|-----|------|
| **C (D+S RRF)** | **65.8%** | **46.0%** | 0.7885 | **65ms** | **현행 최적** |
| E (D+S + CE) | 62.6% (-3.2%p) | 38.0% (-8%p) | 0.1907 | 146ms | **회귀** |

### 0-2. CE 점수 양극화 문제

```
CE Score Distribution (500개 질의의 Top-1):

  0.0 - 0.1: ████████████████████████████████████████  70%
  0.1 - 0.2: ████                                       5%
  0.2 - 0.5: ████████                                  10%
  0.5 - 0.8: ████                                       5%
  0.8 - 1.0: ████████                                  10%
             ─────────────────────────────────────────
             → 이진적 분포: "관련 없음(0)" 또는 "확실히 관련(1)"
             → 중간 점수가 없어 미세한 순위 차이를 감별할 수 없음
```

> **쉬운 비유 — 1차 서류심사 + 2차 면접:**
>
> **이전 (실패한 방식)**: 면접관(CE)의 판단으로 서류심사(RRF) 결과를 **전부 교체**했다.
> 면접관이 대부분의 후보에게 0점 또는 100점만 주니, 서류심사에서 80점/82점/85점으로 미세하게 구분했던 순위가 모두 뭉개졌다.
>
> **새 방식 (점수 퓨전)**: 서류심사 점수 + 면접 점수를 **종합**하여 최종 결정.
> 면접이 이상한 점수를 줘도 서류심사 점수가 균형을 잡아준다.

---

## 1. Cross-Encoder란?

> **쉬운 비유 — Bi-Encoder vs Cross-Encoder:**
>
> **Bi-Encoder** (1차 검색에서 사용):
> 질의와 문서를 **각각 따로** 시험 보게 한 뒤, 성적표(벡터)를 비교한다.
> 빠르지만 질의-문서 간 상호작용을 놓칠 수 있다.
>
> **Cross-Encoder** (리랭킹에서 사용):
> 질의와 문서를 **함께 앉혀서** 면접관이 직접 비교한다.
> 더 정확하지만, 후보 20개를 각각 개별 면접해야 하므로 느리다 (20개 → 20번 추론).
>
> 일반적으로 1차 검색(Bi-Encoder)으로 후보 50개를 빠르게 추리고,
> 2차 리랭킹(Cross-Encoder)으로 Top-K를 정밀 선별한다.

### 현재 사용 모델

| 모델 | 크기 | 한국어 | 비고 |
|------|------|--------|------|
| **dragonkue/bge-reranker-v2-m3-ko** | 568M | O (XLM-R 기반, 한국어 fine-tuned) | 현행 선택 |

---

## 2. 이론적 배경 — 외부 연구

### 2-1. CE 점수 양극화 해결책

Cross-encoder의 이진적 점수 분포 문제에 대한 3가지 해결 방법:

| 방법 | 설명 | 장점 | 단점 |
|------|------|------|------|
| **Min-max 정규화** | `(score - min) / (max - min)` per query | 간단 | outlier에 민감 |
| **Sigmoid 캘리브레이션** | `sigmoid(logit / temperature)` | 분포 조절 가능 | temperature 학습 필요 |
| **Rank-based 퓨전** | CE 점수 무시, CE 순위만 RRF에 사용 | **가장 robust** | 절대 점수 정보 손실 |

**우리 선택**: **Convex Combination (점수 퓨전)** — RRF 순위 점수와 CE 점수를 가중 합산

### 2-2. Score Interpolation α값 (Qdrant Blog, 2024)

```
final_score = α × normalized_rrf_rank + (1 - α) × ce_score
```

> **쉬운 비유 — 대학 입시 종합 점수:**
>
> 서류 평가(RRF)와 면접(CE)의 비중을 정하는 것이 α값이다.
> - α = 0.7이면 서류 70% + 면접 30% → 서류 중시
> - α = 0.3이면 서류 30% + 면접 70% → 면접 중시
> - α = 0.5이면 균등 배분

| 도메인 | 최적 α | 의미 |
|--------|--------|------|
| 일반 (MS MARCO) | 0.3 | CE 70% — CE 신뢰도 높음 |
| **도메인 특화** (부동산 등) | **0.4~0.5** | CE가 도메인 어휘에 약함 → retriever 가중 |
| 다국어/비영어 | 0.5+ | CE가 영어 중심 학습 → retriever 가중 |

**우리 시작점**: α = 0.5 → 그리드 서치로 최적화

### 2-3. RankGPT (Sun et al., EMNLP 2023 — Outstanding Paper Award)

- **논문**: "Is ChatGPT Good at Search? Investigating Large Language Models as Re-Ranking Agents"
- **핵심**: LLM이 listwise로 문서 순위를 재조정 — CE보다 비영어에서 우수
- **정량**: nDCG@10 = 75.0 (TREC-DL19), 기존 CE 대비 +2~5%
- **적용**: 현 단계에서는 비용/레이턴시 과다. 딥 리포트 생성 시 검토 가능
- 출처: https://arxiv.org/abs/2304.09542

### 2-4. 한국어 Reranker 벤치마크 (instructkr, 2025)

14개 reranker 모델, 10개 한국어 검색 데이터셋 (18,945 queries) 평가:

| 순위 | 모델 | MRR@10 | 비고 |
|------|------|--------|------|
| 1 | Qwen3-Reranker-4B | 0.8324 | 4B 파라미터 |
| 2 | Qwen3-Reranker-8B | 0.8275 | 8B 파라미터 |
| 3 | **bge-reranker-v2-m3** | **0.8113** | **568M — 비용 효율 최적** |

출처: https://github.com/instructkr/reranker-simple-benchmark

**bge-reranker-v2-m3-ko** (한국어 fine-tuned 버전):
- Top-1 F1: 0.9123 (base 0.8772 대비 +4.0%)
- 출처: https://huggingface.co/dragonkue/bge-reranker-v2-m3-ko

### 2-5. Score Injection 기법 (IR Journal, 2024)

- **논문**: "Injecting the score of the first-stage retriever as text improves BERT-based re-rankers"
- **핵심**: BM25 점수를 CE 입력에 텍스트로 주입 → 기존 interpolation보다 우수
- **적용**: 향후 고려 가능 (현 단계는 convex combination으로 시작)
- 출처: https://link.springer.com/article/10.1007/s10791-024-09435-8

---

## 3. 점수 퓨전 구현 (pipeline.py)

### 3-1. _rerank_ontology() (pipeline.py L82~117)

> **쉬운 비유 — 점수 표준화:**
>
> 한 학교는 100점 만점, 다른 학교는 10점 만점으로 시험을 본다.
> 두 학교 학생을 비교하려면 먼저 점수를 같은 스케일(0~1)로 변환해야 한다.
> RRF 순위 점수와 CE 점수도 스케일이 다르므로 정규화 후 합산한다.

```python
def _rerank_ontology(
    self,
    query: str,
    candidates: list,
    top_k: int = 5,
    alpha: float = 0.5,
) -> list:
    """P1-b: Cross-Encoder 리랭킹 + RRF 점수 퓨전.

    final_score = alpha * normalized_rrf_rank + (1-alpha) * ce_score

    Args:
        query: 원본 질의 텍스트
        candidates: RRF 결과 리스트 (이미 RRF 순위로 정렬)
        top_k: 최종 반환 개수
        alpha: retriever 가중치 (0.5 = 균등, 1.0 = retriever만)
    """
    if not candidates:
        return []

    # CE 리랭킹 수행
    reranked = rerank_results(query, candidates, top_k=len(candidates))
    if not reranked:
        return candidates[:top_k]

    total = len(candidates)
    fused = []
    for item in reranked:
        # RRF 순위를 0~1로 정규화 (1위=1.0, 최하위=0.0)
        rrf_rank_score = 1.0 - (item.original_rank / max(total, 1))
        # Convex combination
        final = alpha * rrf_rank_score + (1 - alpha) * item.score
        fused.append((final, item))

    fused.sort(key=lambda x: x[0], reverse=True)

    # 원본 point로 복원
    result = []
    for _, item in fused[:top_k]:
        if item.original_rank < len(candidates):
            result.append(candidates[item.original_rank])
        else:
            result.append(candidates[0])
    return result
```

### 3-2. α 그리드 서치

```python
# tune_rerank_alpha.py (신규 스크립트)

ALPHA_GRID = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]

for alpha in ALPHA_GRID:
    results = run_benchmark(setting="full_rerank", alpha=alpha)
    print(f"α={alpha:.1f}: P@3={results['p3']:.1%}, "
          f"Set B={results['set_b_p3']:.1%}, "
          f"Regression={results['regressions']}")
```

> **α 선택 가이드:**
>
> - α < 0.4: CE에 과의존 → CE 양극화 문제가 다시 발생할 위험
> - α = 0.5: 균등 — 시작점으로 적합
> - α > 0.7: retriever에 과의존 → CE를 쓰는 의미가 없어짐
> - **α = 0.4~0.6이 도메인 특화 RAG의 일반적 최적 범위**

---

## 4. 벤치마크 실행

```bash
# 기본 실행 (α=0.5)
python3 codes/query/test_query_decomposition.py \
    --set all \
    --setting full_rerank \
    --output results/p1b_step5_rerank.json

# α 그리드 서치 (선택, ~4.2시간)
python3 codes/query/tune_rerank_alpha.py \
    --alpha-range 0.3,0.8,0.1 \
    --output results/p1b_alpha_grid.json
```

---

## 5. 성공 기준

| 기준 | 임계값 | 근거 |
|------|--------|------|
| 전체 P@3 | ≥ 65.8% (Baseline 이상) | CE 재도입이 회귀를 일으키지 않아야 함 |
| Avg Top-1 | ≥ 0.7885 + 0.02 | CE의 정밀 매칭이 Top-1 품질을 개선해야 의미 |
| Set B P@3 | ≥ Step 4 결과 | 구어체에서 CE가 추가 효과 |
| Latency p95 | ≤ 250ms | CE 추론 시간 포함 |

---

## 6. 폴백 계획 (3단계)

α 전범위에서 개선 없을 경우:

| 폴백 | 전략 | 근거 |
|------|------|------|
| **폴백 1** | REWRITE 질의에만 CE 적용 (SIMPLE bypass) | CE가 구어체 변환 후에만 효과적일 수 있음 |
| **폴백 2** | Top-3은 RRF 유지, 4~20위만 CE 리랭킹 | Top-3 안정성 보호 |
| **폴백 3** | CE 없이 Step 1~4 결과만으로 운영 | CE 자체가 현 데이터셋에서 비효과적이면 포기 |

---

## 7. 절대 하지 말 것

- **CE 점수를 정규화 없이 직접 사용** — 이진적 분포로 순위가 뭉개짐
- **CE 결과로 RRF 결과를 전면 교체** — Setting E 실패의 근본 원인
- **α를 0.2 이하로 설정** — CE 과의존, 양극화 문제 재발
- **CE 모델을 검증 없이 변경** — bge-reranker-v2-m3-ko가 한국어 최적 확인됨

---

## 8. 실행 체크리스트

- [ ] `pipeline.py` _rerank_ontology()에서 점수 퓨전 로직 확인
- [ ] `pipeline.py` search()에서 rerank=True 시 정상 동작 확인
- [ ] 단위 테스트: α=0.5에서 CE 추가 시 Top-3 변화 확인
- [ ] 500개 벤치마크 실행 (α=0.5)
- [ ] (선택) α 그리드 서치 실행
- [ ] 결과 분석: P@3 ≥ 65.8%, Avg Top-1 개선 확인

---

## 9. 참고 문헌

| 자료 | 출처 |
|------|------|
| RankGPT (Sun et al., EMNLP 2023) | https://arxiv.org/abs/2304.09542 |
| bge-reranker-v2-m3 (BAAI, 2024) | https://huggingface.co/BAAI/bge-reranker-v2-m3 |
| bge-reranker-v2-m3-ko (dragonkue) | https://huggingface.co/dragonkue/bge-reranker-v2-m3-ko |
| Korean Reranker Benchmark (instructkr) | https://github.com/instructkr/reranker-simple-benchmark |
| Score Injection (IR Journal, 2024) | https://link.springer.com/article/10.1007/s10791-024-09435-8 |
| Cross-Encoders vs LLMs (Naver Labs, 2024) | https://arxiv.org/abs/2403.10407 |
| Qdrant DBSF (Distribution-Based Score Fusion) | https://github.com/qdrant/qdrant/pull/4614 |
| Sentence Transformers Cross-Encoder docs | https://sbert.net/docs/cross_encoder/usage/usage.html |
