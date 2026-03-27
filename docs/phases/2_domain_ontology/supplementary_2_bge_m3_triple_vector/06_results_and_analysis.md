# BGE-M3 Triple-Vector 결과 분석

> 작성일: 2026-03-27
> 선행 문서: `01_bgem3_triple_vector_plan.md` ~ `05_benchmark_and_ablation.md`
> 목적: 벤치마크 결과 기록, v1 vs v2 비교 분석, 다음 단계 도출

---

## 1. 실행 환경

| 항목 | 값 |
|------|---|
| 테스트 일자 | 2026-03-27 |
| 하드웨어 | DGX Spark (GB10), 128GB unified |
| Qdrant 버전 | v1.17.0 |
| BGE-M3 모델 | BAAI/bge-m3 (FP16, FlagEmbedding 1.3.5) |
| KURE-v1 모델 | nlpai-lab/KURE-v1 (SentenceTransformer) |
| 질의 수 | 온톨로지 25개 + 법률 20개 = 45개 |
| v2 컬렉션 | domain_ontology_v2 (2,146점), legal_docs_v2 (775점) |

---

## 2. 벤치마크 결과

### 2-1. 종합 비교표

| 설정 | Onto P@3 | Onto Avg Top-1 | Legal Avg Top-1 | Latency p95 |
|------|----------|---------------|-----------------|-------------|
| A: v1 KURE-v1 + Kiwi BM25 | 84% | 0.6192 | 0.6119 | — |
| B: v2 BGE-M3 Dense only | 80% | 0.6332 | 0.6561 | 45ms |
| **C: v2 BGE-M3 D+S RRF** | **92%** | **0.7907** | **0.7338** | **48ms** |
| D: v2 BGE-M3 D+S+ColBERT | 72% | 6.66* | 7.19* | 60ms |

> *ColBERT MaxSim 점수는 코사인 유사도(0~1)와 다른 스케일(토큰 수 × 유사도 합산)이므로 직접 비교 불가.

### 2-2. 성공 기준 달성 여부 (설정 C 기준)

| 지표 | 목표 | 결과 | 달성 |
|------|------|------|------|
| Precision@3 (전체 25개) | ≥ 90% | **92%** | **달성** |
| Avg Top-1 Ontology | ≥ 0.72 | **0.7907** | **달성** (+27.7%) |
| Avg Top-1 Legal | ≥ 0.70 | **0.7338** | **달성** (+19.9%) |
| Latency p95 | < 200ms | **48ms** | **달성** |

**모든 성공 기준 달성.**

---

## 3. Ablation 분석

### 3-1. 각 구성 요소의 기여도

| 추가 요소 | Onto P@3 변화 | Onto Top-1 변화 | Legal Top-1 변화 |
|-----------|-------------|----------------|-----------------|
| BGE-M3 Dense (vs KURE-v1) | A→B: 84%→80% (-4%p) | 0.619→0.633 (+2.3%) | 0.612→0.656 (+7.2%) |
| **+ Sparse (학습 어휘 가중치)** | **B→C: 80%→92% (+12%p)** | **0.633→0.791 (+24.9%)** | **0.656→0.734 (+11.9%)** |
| + ColBERT (토큰별 리랭킹) | C→D: 92%→72% (-20%p) | 점수 스케일 다름 | 점수 스케일 다름 |

### 3-2. 핵심 발견

#### BGE-M3 Sparse가 압도적 기여자

Dense+Sparse RRF(설정 C)에서 **Precision@3이 80%→92%로 +12%p 향상**된 것은 BGE-M3 Sparse 벡터의 **학습된 동의어 확장** 덕분이다. 기존 Kiwi BM25는 정확한 형태소만 매칭했지만, BGE-M3 Sparse는 "세금"→"취득세", "보유세", "재산세" 등 관련 용어를 자동 활성화한다.

**구체적 개선 사례** (v1 실패 → v2 성공):
- "집 그냥 갖고만 있어도 매년 뭐 내야돼?" → 재산세 Top-1 (v1: 종합소득세)
- "부모님 집 물려받으면 비용이 얼마나 들어" → 상속세 Top-1 (v1: 부담부증여)
- "집 팔고 남은 돈에서 세금 떼가나" → 양도소득세 Top-1 (v1: 양도비용)

#### BGE-M3 Dense는 KURE-v1보다 약간 낮음

Dense 단독(설정 B)에서 P@3이 80%로, KURE-v1(84%)보다 4%p 낮았다. 이는 예상대로 KURE-v1이 한국어 Dense 전용 fine-tune의 이점을 가지기 때문이다. 그러나 Sparse를 추가하면 이 차이를 크게 넘어선다.

#### ColBERT 리랭킹은 현재 효과적이지 않음

설정 D(ColBERT 리랭킹)에서 P@3이 72%로 오히려 하락했다. 원인 분석:

1. **점수 스케일 차이**: ColBERT MaxSim 점수(토큰별 유사도 합산)는 0~수십 범위. Dense/Sparse의 RRF 점수(0~1 범위)와 동일한 기준으로 재정렬하면 순서가 왜곡된다.
2. **Qdrant의 nested prefetch + ColBERT 조합**: 현재 구현에서는 prefetch로 뽑힌 후보들을 ColBERT 점수만으로 재정렬하는데, RRF로 잘 뽑힌 순서를 ColBERT가 뒤집어버리는 문제가 있다.
3. **해결 방안**:
   - RRF 퓨전 후 ColBERT를 적용하려면 Qdrant의 nested prefetch를 2단계로 구성 필요
   - 또는 ColBERT를 서버 사이드가 아닌 클라이언트 사이드에서 적용
   - 또는 Cross-Encoder(bge-reranker-v2-m3)로 대체

---

## 4. 실패 질의 분석 (설정 C: hybrid_rrf)

### 4-1. 여전히 실패하는 질의 (2/25 = 8%)

| 질의 | Top-3 결과 | 기대 키워드 | 실패 원인 |
|------|-----------|-----------|----------|
| "부동산 사면 나라에 돈 내야 되나" | 공과금, 속지주의, 납세의무 | 취득세, 세금 | 극단적 구어체("나라에 돈") |
| "은행에서 집값의 몇 프로까지 빌려주는지" | 시장이자율, 임차료, 이자 | LTV, 담보, 대출 | 개념 격차("빌려주는"↔"LTV") |

### 4-2. Contextual Retrieval(P0-a) 대비 개선 현황

| 기존 실패 질의 (P0-a 테스트) | P0-a 결과 | P0-b(현재) 결과 | 개선 |
|----------------------------|----------|----------------|------|
| "부동산 사면 나라에 돈 내야 되나" | X (공과금) | X (공과금) | 미해결 |
| "은행에서 집값의 몇 프로까지 빌려주는지" | X (시장이자율) | X (시장이자율) | 미해결 |
| "월세 올려달라는데 한도가 있어?" | X (임차료) | **O** (차임증감청구권) | **해결** |

### 4-3. 실패 원인 분류

| 원인 | 질의 수 | 해결 방안 |
|------|---------|----------|
| 극단적 구어체 격차 (W2) | 2 | Query Rewriting (LLM으로 질의 변환) |
| Cross-domain 질의 (W1) | 0 | - |

---

## 5. 저장 용량 및 성능 측정

### 5-1. 컬렉션 통계

| 컬렉션 | 포인트 수 | 벡터 구성 |
|--------|----------|----------|
| domain_ontology_v2 | 2,146 | Dense(1024D) + Sparse(BGE-M3) + ColBERT(multi-vec, INT8) |
| legal_docs_v2 | 775 | 동일 |

### 5-2. 임베딩 성능

| 항목 | 값 |
|------|---|
| BGE-M3 모델 로드 | ~5초 (캐시 후) |
| 2,146 엔트리 임베딩 (3종) | ~14초 |
| 775 청크 임베딩 (3종) | ~12초 |
| 처리량 | ~5-9 docs/sec |

### 5-3. 검색 레이턴시 (hybrid_rrf)

| 지표 | 값 |
|------|---|
| p50 | 8.3ms |
| p95 | 48.0ms |
| max | ~50ms |

→ 실서비스 기준 매우 빠름. RRF 퓨전 오버헤드가 거의 없다.

---

## 6. 성과 궤적 (Phase 2 누적)

```
Phase 2 검색 성능 개선 궤적:

Precision@3:
  Baseline (Phase 2 초기):     80%
  + Contextual Retrieval (P0-a): 90%  (+10%p)
  + BGE-M3 D+S RRF (P0-b):    92%  (+2%p)   ← 현재

Avg Top-1 Ontology:
  Baseline:                    0.611
  + Contextual Retrieval:      0.630  (+3.1%)
  + BGE-M3 D+S RRF:           0.791  (+25.6%)  ← 현재

Avg Top-1 Legal:
  Baseline:                    0.616
  + Contextual Retrieval:      0.648  (+5.2%)
  + BGE-M3 D+S RRF:           0.734  (+13.3%)  ← 현재
```

---

## 7. 다음 단계 연결

| 우선순위 | 작업 | 이 결과에서 도출된 근거 |
|---------|------|---------------------|
| **P1-a** | Query Rewriting / Decomposition | 2개 실패 질의가 극단적 구어체 문제 — LLM으로 질의를 전문용어로 변환하면 해결 가능 |
| P1-b | ColBERT 리랭킹 개선 | 현재 ColBERT가 오히려 성능 저하 — nested prefetch 2단계 구성 또는 Cross-Encoder 대체 검토 |
| P2-a | Intent Classifier + Query Router | "나라에 돈"→세금 브랜치, "빌려주는"→대출 브랜치로 라우팅하면 실패 질의 해결 가능 |
| P2-b | Cross-Encoder Reranking | ColBERT 대신 bge-reranker-v2-m3 사용 검토 — 정확도 더 높으나 레이턴시 증가 |

---

## 8. 결론

### 8-1. BGE-M3 Dense+Sparse RRF가 최적 설정

- **Precision@3 92%** (목표 90% 달성), **Top-1 0.791** (목표 0.72 대폭 초과)
- 레이턴시 p95 48ms로 실서비스 수준
- 핵심 요인: BGE-M3 Sparse의 **학습된 동의어 확장**이 구어체↔전문용어 매핑 문제를 대폭 개선

### 8-2. ColBERT는 추가 조정 필요

- 현재 구현에서는 RRF 퓨전 결과를 ColBERT가 뒤집어 성능 하락
- Qdrant nested prefetch 2단계 또는 Cross-Encoder 대체 필요
- 당장은 Dense+Sparse RRF(설정 C)를 프로덕션 설정으로 채택

### 8-3. 권장 사항

1. **즉시**: `domain_ontology_v2` + `legal_docs_v2`를 Dense+Sparse RRF 모드로 운영
2. **다음 작업**: P1-a Query Rewriting으로 남은 2개 실패 질의 해결
3. **추후**: ColBERT 리랭킹 또는 Cross-Encoder로 정밀도 추가 향상 시도
