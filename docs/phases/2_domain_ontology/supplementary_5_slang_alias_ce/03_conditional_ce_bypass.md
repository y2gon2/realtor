# CE 양극화 대응 — 조건부 우회 + 점수 정규화

> 작성일: 2026-03-28
> 선행 문서: `01_phase2a_quickwins_plan.md`, `02_alpha_grid_search.md`
> 관련 코드: `codes/query/pipeline.py`, `codes/query/config.py`, `codes/embedding/reranker.py`
> 목적: CE 점수 양극화 문제를 해결하여 Set B P@3 56% → 60%+ 개선

---

## 1. 문제 상세 분석

### 1-1. CE 양극화의 원인

> **비유**: 시험 채점자가 "맞다(100점)" 또는 "틀리다(0점)"만 줄 수 있고, "부분 점수(50점)"를 줄 수 없는 상황이다.

Cross-Encoder(`bge-reranker-v2-m3-ko`)는 **Binary Cross-Entropy (BCE) loss**로 학습되었다:

```
BCE Loss = -[y × log(p) + (1-y) × log(1-p)]

여기서:
  y = 정답 라벨 (1=관련, 0=무관)
  p = 모델 예측 확률 (sigmoid 출력)
```

이 손실 함수의 특성:
- y=1일 때: p가 1에 가까울수록 loss가 0 → **관련 문서는 1.0으로 밀림**
- y=0일 때: p가 0에 가까울수록 loss가 0 → **무관 문서는 0.0으로 밀림**
- 결과: 중간 값(0.3~0.7)이 거의 없는 **이진 분포(bimodal distribution)**

### 1-2. 왜 구어체에서 특히 문제인가?

CE 모델의 학습 데이터(MS MARCO, MIRACL)는 대부분 **정규 질의-문서 쌍**이다:

```
학습 데이터 예시:
  질의: "How to calculate property tax?"
  문서: "Property tax is calculated by multiplying..."
  라벨: 1 (관련)
```

극단 구어체 질의는 학습 데이터에 없는 **분포 외(Out-of-Distribution, OOD)** 패턴:

```
OOD 질의:
  질의: "나라에 돈 내야 되나"
  문서: "취득세는 부동산을 취득할 때 납부하는..."
  CE 판정: 0.01 (무관) ← 실제로는 관련!
```

CE가 이 쌍을 "무관"으로 판정하면, 원래 RRF에서 1위였던 정답이 CE에 의해 밀려나게 된다.

### 1-3. 데이터로 본 영향

| 비교 | Set B P@3 | 차이 | 분석 |
|------|----------|------|------|
| Full (Step 1-4, CE 없음) | **58%** | 기준선 | LLM Query Rewriting 효과 |
| Full+Rerank (CE 퓨전) | **56%** | **-2%p** | CE가 정답을 밀어냄 |

→ CE를 적용하면 오히려 성능이 떨어지는 역설적 상황.

---

## 2. 해결 전략 — 2단계 접근

### 2-1. 전체 구조

```
[질의 입력]
    │
    ▼
[Step 1: CE 스킵 여부 결정]
    │
    ├── 스킵 조건 충족 → CE 리랭킹 건너뛰기 → RRF 결과 그대로 반환
    │
    └── 스킵 아님 → [Step 2: 조건부 α로 CE 적용]
                         │
                         └── CE 점수 min-max 정규화 후 퓨전
```

### 2-2. Step 2-A: 조건부 CE 우회

> **비유**: 면접관이 "외국어 면접"에 약한 것을 알면, 외국어 능력이 필요한 직무에서는 면접 대신 포트폴리오 평가로 대체하는 것.

**스킵 조건**:

| 조건 | 임계값 | 이유 |
|------|--------|------|
| colloquial_score ≥ 3 | `COLLOQUIAL_SKIP_THRESHOLD` | 극단 구어체: CE가 판별 불가 |
| REWRITE + colloquial_score ≥ 2 | `REWRITE_SKIP_THRESHOLD` | 변환된 질의도 CE와 궁합 불량 |

**왜 이 임계값인가?**

colloquial_score 분포 (500개 질의):

```
score=0: ████████████████████  약 300개 (정규 질의)
score=1: ████████              약 80개  (약간 구어체)
score=2: ██████                약 60개  (구어체)
score=3: ████                  약 40개  (극단 구어체)
score=4+: ██                   약 20개  (슬랭/비격식)
```

- score ≥ 3: 약 60개 (12%) — 이 질의들에서 CE가 주로 역효과
- score ≥ 2 + REWRITE: 추가 약 30개 — REWRITE 후에도 CE가 부정확

### 2-3. 구현 코드

```python
# codes/query/config.py
COLLOQUIAL_SKIP_THRESHOLD = 3   # colloquial_score >= 3 → CE 스킵
REWRITE_SKIP_THRESHOLD = 2      # REWRITE + cs >= 2 → CE 스킵
```

```python
# codes/query/pipeline.py
def _should_skip_rerank(self, analysis: QueryAnalysis, query: str) -> bool:
    """Phase 2A: 극단 구어체 질의에서 CE 리랭킹 스킵 여부 결정.

    AcuRank (2025) 논문의 적응적 리랭킹 원리 적용:
    - 확실히 CE가 도움이 안 되는 질의에서는 리랭커를 호출하지 않음
    - 리랭커 호출 약 12% 감소, 구어체 세트 회귀 방지
    """
    cs = self.analyzer._colloquial_score(query)

    # 조건 1: 극단 구어체 (마커 3개+ 또는 마커 1개 + 전문용어 0)
    if cs >= COLLOQUIAL_SKIP_THRESHOLD:
        return True

    # 조건 2: LLM이 REWRITE했지만 여전히 구어체 느낌
    if analysis.type == "REWRITE" and cs >= REWRITE_SKIP_THRESHOLD:
        return True

    return False
```

**`search()` 메서드에서의 적용**:

```python
# Step 3 (SIMPLE 질의)와 Step 6 (REWRITE/DECOMPOSE 질의) 모두에서:
if rerank and onto_final and not skip_rerank:
    onto_final = self._rerank_ontology(
        query, onto_final, top_k=limit, alpha=effective_alpha,
    )
# skip_rerank가 True이면 RRF 결과를 CE 없이 그대로 반환
```

---

## 3. Step 2-B: CE 점수 Min-Max 정규화

### 3-1. 개념

> **비유**: 시험 점수가 0~100점인데, 학생 대부분이 0점 또는 95점만 받는 상황에서, "이 반에서의 상대적 위치"로 재채점하는 것.

CE 점수의 raw 값 예시 (한 질의에 대한 20개 후보):

```
후보:  A     B     C     D     E     ... (20개)
raw:  0.01  0.00  0.85  0.00  0.00  ...
```

**문제**: 대부분이 0에 가까워서, A(0.01)와 B(0.00)의 차이가 극히 미미.
RRF rank score(0~1 균등 분포)와 합산하면 CE의 영향이 미미해짐.

**Per-Query Min-Max 정규화** 후:

```
min = 0.00, max = 0.85, range = 0.85

후보:  A       B       C       D       E
raw:  0.01    0.00    0.85    0.00    0.00
norm: 0.012   0.000   1.000   0.000   0.000
```

→ 최고 점수 후보(C)가 1.0으로, 최저가 0.0으로 정규화.
→ RRF rank score와 동일한 0~1 스케일에서 convex combination 가능.

### 3-2. 수학적 정의

```
normalized_ce(x) = (x - min(scores)) / (max(scores) - min(scores))

여기서:
  x = 개별 후보의 CE raw score
  min(scores) = 해당 질의의 모든 후보 중 최소 CE 점수
  max(scores) = 해당 질의의 모든 후보 중 최대 CE 점수
```

**Edge case**: `max == min`이면 (모든 후보가 동일 점수) → `ce_range = 1.0`으로 설정하여 0으로 나누기 방지.

### 3-3. 구현 코드

```python
# codes/query/pipeline.py — _rerank_ontology() 수정
def _rerank_ontology(self, query, candidates, top_k=5, alpha=0.5):
    """P1-b: Cross-Encoder 리랭킹 + RRF 점수 퓨전.

    Phase 2A 개선: Per-query min-max normalization으로 CE 이진 분포 완화.
    """
    if not candidates:
        return []

    reranked = rerank_results(query, candidates, top_k=len(candidates))
    if not reranked:
        return candidates[:top_k]

    # ── Phase 2A: CE 점수 per-query min-max 정규화 ──
    ce_scores = [item.score for item in reranked]
    ce_min = min(ce_scores)
    ce_max = max(ce_scores)
    ce_range = ce_max - ce_min if ce_max > ce_min else 1.0

    total = len(candidates)
    fused = []
    for item in reranked:
        # RRF 순위 점수: 1위=1.0, 20위=0.0
        rrf_rank_score = 1.0 - (item.original_rank / max(total, 1))
        # CE 정규화 점수: 해당 질의 내에서 0.0~1.0
        normalized_ce = (item.score - ce_min) / ce_range
        # 최종 퓨전
        final = alpha * rrf_rank_score + (1 - alpha) * normalized_ce
        fused.append((final, item))

    fused.sort(key=lambda x: x[0], reverse=True)

    # RerankItem → 원본 point 형태로 복원
    result = []
    for _, item in fused[:top_k]:
        if item.original_rank < len(candidates):
            result.append(candidates[item.original_rank])
        else:
            result.append(candidates[0])
    return result
```

### 3-4. 정규화 전후 비교 예시

α=0.5일 때:

```
── 정규화 전 (기존) ──
후보  RRF순위점수  CE raw  최종점수    순위
C     0.85        0.85    0.850      1위
A     0.95        0.01    0.480      2위  ← RRF 1위인데 CE가 끌어내림
D     0.80        0.00    0.400      3위

── 정규화 후 (Phase 2A) ──
후보  RRF순위점수  CE norm  최종점수    순위
C     0.85        1.000    0.925      1위
A     0.95        0.012    0.481      2위  ← 거의 동일
D     0.80        0.000    0.400      3위
```

정규화가 큰 차이를 만들지 않는 것처럼 보이지만, **CE 점수가 더 미묘하게 분포하는 경우**(예: 0.01 vs 0.03 vs 0.05) 정규화가 이 차이를 확대하여 CE의 변별력을 살린다.

---

## 4. Phase 2B 예고 — Isotonic Regression

> **참고**: 아래 내용은 Phase 2A의 범위를 초과하므로 Phase 2B에서 구현 예정.

### 4-1. 왜 Isotonic Regression이 더 좋은가?

> **비유**: Min-Max 정규화가 "이 반에서 몇 등인지"만 보는 거라면, Isotonic Regression은 "과거 시험 결과를 참고해서 이 점수가 실제로 합격 확률이 몇 %인지" 예측하는 것이다.

**Platt Scaling** (시그모이드 보정):
- 가정: 점수 분포가 시그모이드 형태
- 우리 문제: **이진 분포(bimodal)**이므로 시그모이드 가정 위반 → 부적합

**Isotonic Regression** (단조 보정):
- 가정: **없음** (비모수적 방법)
- 원리: "CE 점수가 높을수록 실제 관련성이 높다"는 단조(monotone) 제약만 부과
- 학습: (CE score, 정답 라벨) 쌍 1,000개 이상으로 보정 함수 학습
- Niculescu-Mizil & Caruana (2005): 18/20 테스트에서 Platt 대비 우수

```python
# Phase 2B 예시 코드 (sklearn)
from sklearn.isotonic import IsotonicRegression

# 학습 데이터: 500개 질의 × 20 후보 = 10,000 쌍
ce_scores = [...]       # CE raw scores
labels = [...]          # 1(정답) 또는 0(오답)

ir = IsotonicRegression(out_of_bounds="clip")
ir.fit(ce_scores, labels)

# 보정: 새 CE 점수 → 실제 관련 확률
calibrated = ir.predict(new_ce_scores)
```

---

## 5. 검증 계획

### 5-1. CE 스킵 비율 확인

```bash
# full_rerank 벤치마크 실행 시 스킵 로그 출력
python3 test_query_decomposition.py --setting full_rerank
```

기대 CE 스킵 분포:

| 세트 | CE 적용 | CE 스킵 | 스킵율 |
|------|--------|--------|--------|
| A (150) | ~145 | ~5 | ~3% |
| B (50) | ~20 | ~30 | ~60% |
| C (100) | ~95 | ~5 | ~5% |
| D (100) | ~60 | ~40 | ~40% |
| E (100) | ~70 | ~30 | ~30% |

### 5-2. 성공 기준

| 지표 | 현재 | 목표 |
|------|------|------|
| Set B P@3 | 56% | ≥58% (Full 수준 복원) |
| Set A P@3 | 79% | ≥79% (회귀 없음) |
| 전체 P@3 | 68.0% | ≥70% (작업 1+2 합산) |
| CE 스킵율 | 0% | ~25% (구어체 집중) |
