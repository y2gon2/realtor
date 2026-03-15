# Phase 1.1 — 임베딩 데이터 테스트

## 개요

KURE-v1 모델로 rag_v2 문서 약 6,000개를 Qdrant(`realestate_v2` 컬렉션)에 색인 완료한 상태에서,
임베딩 품질과 검색 성능을 검증하는 단계이다.

**목표:** RAG 파이프라인 다음 단계(LLM 연동)로 넘어가기 전에, 검색 레이어가 신뢰할 수 있는 수준인지 확인

### 환경

| 항목 | 값 |
|---|---|
| 임베딩 모델 | KURE-v1 (1024D, L2 정규화) |
| 벡터 DB | Qdrant v1.17.0 |
| 컬렉션 | `realestate_v2` (Dense + Sparse BM25) |
| 청크 타입 | summary, atomic_fact, hyde |
| 컨테이너 | `rag-embedding` (NGC PyTorch) |
| 테스트 스크립트 | `codes/embedding/search_test.py`, `codes/embedding/quality_eval.py` |

---

## 1. 시맨틱 검색 테스트

**목적:** 자연어 질의로 관련 문서를 정확히 검색하는지 확인

### 테스트 스크립트

`codes/embedding/search_test.py`

### 실행 방법

```bash
# 컨테이너 접속
docker exec -it rag-embedding bash

# ── 단일 질의 테스트 ──
python codes/embedding/search_test.py \
    --query "강남구 재건축 투자 전망"

# ── 내장 테스트셋 배치 실행 ──
python codes/embedding/search_test.py

# ── 전체 테스트 (배치 + 필터 + chunk_type 비교) ──
python codes/embedding/search_test.py --all

# ── JSON 결과 저장 ──
python codes/embedding/search_test.py --all \
    --json-output /workspace/search_test_results.json
```

### Dense vs Hybrid 비교

| 모드 | 설명 | 장점 |
|---|---|---|
| Dense | KURE-v1 벡터만으로 코사인 유사도 검색 | 의미적 유사성에 강함 |
| Hybrid | Dense + Sparse(BM25) → RRF 융합 | 키워드 매칭 + 의미 검색 결합 |

**확인 포인트:**
- Dense top-1 결과가 질의 의도와 부합하는가
- Hybrid가 Dense 대비 추가로 잡아내는 관련 문서가 있는가
- 두 모드의 결과 일치율 (overlap rate)

### 내장 테스트 질의셋 (16개)

| # | 질의 | 테스트 의도 |
|---|---|---|
| 1 | 강남구 아파트 시세 전망은 어떤가요? | 지역 + 자산 타입 검색 |
| 2 | 전세사기 예방하려면 어떻게 해야 하나요? | 실용 정보 검색 |
| 3 | 재건축 초과이익환수제가 뭔가요? | 정책/제도 설명 검색 |
| 4 | DSR 규제가 대출한도에 미치는 영향 | 금융 규제 검색 |
| 5 | 생애최초 주택 구입 시 혜택 | 지원 정책 검색 |
| 6 | 경매 낙찰가율이 높은 지역 | 데이터 기반 질의 |
| 7 | 다주택자 양도소득세 중과 기준 | 세금 정책 검색 |
| 8 | 신축 아파트 청약 당첨 전략 | 전략/노하우 검색 |
| 9 | 집값이 오를 곳을 어떻게 찾나요? | 간접적 표현 (의미 검색 품질) |
| 10 | 월세 살다가 내 집 마련하는 방법 | 간접적 표현 (의미 검색 품질) |
| 11 | 경매 입찰 참여시 고려해야하는 법률 사항 |  |
| 13 | 경매 입찰 참여시 고려해야하는 비 법률적 사항 |  |
| 14 | 좋은 중학교를 다닌 수 있는 아파트 |  |
| 15 | 최신 부동산 정책으로 수혜가 예상되는 지역 |  |
| 16 | 인천에 호재가 많은 지역과 아파트 단지 |  |
---

## 2. 메타데이터 필터링 검색

**목적:** 메타데이터 필터와 시맨틱 검색을 결합하여 정밀 검색이 가능한지 확인

### 실행 방법

```bash
# topic_tags 필터
python codes/embedding/search_test.py \
    --query "아파트 당첨 전략" \
    --topic-tag "청약/분양"

# region_tags 필터
python codes/embedding/search_test.py \
    --query "재건축 투자" \
    --region-tag "서울/강남구"

# chunk_type 필터
python codes/embedding/search_test.py \
    --query "전세사기 예방법" \
    --chunk-type summary

# 복합 필터 (chunk_type + topic_tag)
python codes/embedding/search_test.py \
    --query "청약 당첨 전략" \
    --chunk-type summary \
    --topic-tag "청약/분양"

# channel 필터
python codes/embedding/search_test.py \
    --query "부동산 시장 전망" \
    --channel "jachinam"
```

### 사용 가능한 필터 필드

| 필드 | 타입 | 예시 값 |
|---|---|---|
| `chunk_type` | keyword | `summary`, `atomic_fact`, `hyde` |
| `topic_tags` | keyword | `청약/분양`, `임장/현장분석`, `재건축/재개발`, `전세/월세` 등 |
| `region_tags` | keyword | `서울/강남구`, `서울/성북구`, `경기/수원시` 등 |
| `asset_type` | keyword | `아파트`, `오피스텔`, `빌라/다세대`, `토지` 등 |
| `channel` | keyword | 유튜브 채널명 |

### 확인 포인트

- 필터 적용 시 결과가 해당 카테고리로 정확히 한정되는가
- 필터링 후에도 시맨틱 유사도 순서가 합리적인가
- 복합 필터 시 결과 수가 지나치게 적지 않은가 (데이터 커버리지)

---

## 3. 임베딩 품질 평가

**목적:** KURE-v1 임베딩이 부동산 도메인에서 의미적 구분을 잘 하는지 정량 평가

### 테스트 스크립트

`codes/embedding/quality_eval.py`

### 실행 방법

```bash
# 전체 평가 실행
python codes/embedding/quality_eval.py

# JSON 리포트 저장
python codes/embedding/quality_eval.py \
    --json-output /workspace/eval_report.json

# 호스트에서 직접 실행 시
python codes/embedding/quality_eval.py \
    --qdrant-url http://localhost:6333
```

### 평가 방법론

#### 3-1. 유사 질의 쌍 테스트 (8쌍)

같은 의도의 다른 표현으로 검색했을 때 **비슷한 결과**가 나와야 한다.

| 질의 A | 질의 B |
|---|---|
| 전세사기 예방하려면 어떻게 해야 하나요? | 전세 계약할 때 사기 안 당하는 방법 |
| 강남구 아파트 시세 전망 | 강남 부동산 가격이 앞으로 어떻게 될까요? |
| 재건축 초과이익환수제 설명 | 재건축 부담금이 뭔가요? |
| DSR 규제가 대출한도에 미치는 영향 | 총부채원리금상환비율 때문에 대출이 줄어드나요? |
| 생애최초 주택 구입 혜택 | 처음 집 살 때 받을 수 있는 지원 |
| 경매 투자 시 주의사항 | 법원 경매로 집 살 때 조심할 점 |
| 다주택자 세금 중과 | 집 여러 채 가진 사람 세금 불이익 |
| 신축 아파트 청약 전략 | 새 아파트 분양받는 노하우 |

**기대:** cosine similarity 높음, overlap@5/10 높음

#### 3-2. 비유사 질의 쌍 테스트 (4쌍)

서로 다른 주제의 질의는 **다른 결과**가 나와야 한다.

| 질의 A | 질의 B |
|---|---|
| 전세사기 예방법 | 상업용 부동산 투자 수익률 |
| 강남구 아파트 시세 | 농지 전용 허가 절차 |
| 재건축 초과이익환수제 | 월세 세액공제 방법 |
| 경매 낙찰가율 | 신혼부부 특별공급 자격 |

**기대:** cosine similarity 낮음, overlap@5/10 낮음

#### 3-3. chunk_type별 검색 성능 비교

동일 질의에 대해 chunk_type을 필터링하여 각 타입의 검색 점수를 비교한다.

| chunk_type | 설계 의도 | 기대 특성 |
|---|---|---|
| `summary` | 문서 전체 맥락 파악 | 넓은 주제 질의에 강함 |
| `atomic_fact` | 개별 사실 정밀 검색 | 구체적 사실 질의에 강함 |
| `hyde` | 예상 검색 질문 | 자연어 질문과 정렬 강함 |

### 평가 메트릭

| 메트릭 | 설명 | 기준 |
|---|---|---|
| **코사인 유사도** | 두 질의 임베딩 간 거리 | 유사 쌍 > 0.7, 비유사 쌍 < 0.5 |
| **Overlap@5** | top-5 결과 문서 겹침 비율 | 유사 쌍 > 40% |
| **Overlap@10** | top-10 결과 문서 겹침 비율 | 유사 쌍 > 30% |
| **판별력 (Discrimination)** | 유사 평균 cos - 비유사 평균 cos | > 0.15 우수, > 0.08 양호 |
| **avg_top1_score** | chunk_type별 top-1 검색 점수 평균 | 타입 간 차이 확인용 |

### 평가 등급 기준

| 등급 | 판별력 (cosine) | 의미 |
|---|---|---|
| **우수** | > 0.15 | 임베딩이 도메인 의미를 잘 구분함. 다음 단계 진행 가능 |
| **양호** | 0.08 ~ 0.15 | 기본적 구분은 되나, 일부 주제에서 혼동 가능. 주의하며 진행 |
| **개선 필요** | < 0.08 | 임베딩 또는 청크 전략 재검토 필요 |

---

## 4. RAG 파이프라인 구성 (다음 단계)

검색 레이어 검증이 완료되면 LLM을 연동하여 질의응답 시스템을 구성한다.

### 파이프라인 흐름

```
사용자 질의
  → KURE-v1 임베딩
  → Qdrant 검색 (Dense/Hybrid + 메타데이터 필터)
  → 검색 결과 top-K 추출
  → LLM 프롬프트에 컨텍스트로 주입
  → 답변 생성
```

### 검색 → LLM 연동 시 결정 사항

| 항목 | 선택지 | 결정 기준 |
|---|---|---|
| 검색 모드 | Dense / Hybrid | 테스트 결과 비교 후 결정 |
| top-K | 3 ~ 10 | 컨텍스트 길이 vs 정보량 트레이드오프 |
| chunk_type 전략 | 단일 / 혼합 | chunk_type별 성능 테스트 결과 기반 |
| 필터 전략 | 없음 / 자동 태그 추출 | 질의에서 메타데이터 자동 추출 가능 여부 |

---

## 테스트 실행 체크리스트

### 사전 조건

- [ ] `docker compose up -d` 로 Qdrant + embedding 컨테이너 실행 중
- [ ] Qdrant `realestate_v2` 컬렉션에 데이터 색인 완료
- [ ] `docker exec -it rag-embedding bash` 로 컨테이너 접속 가능

### 테스트 순서

```
1. 컬렉션 상태 확인
   $ python codes/embedding/upserter.py

2. 시맨틱 검색 기본 테스트
   $ python codes/embedding/search_test.py

3. 단일 질의 상세 테스트 (Dense vs Hybrid 비교)
   $ python codes/embedding/search_test.py --query "강남구 재건축 투자 전망"

4. 메타데이터 필터링 테스트
   $ python codes/embedding/search_test.py --all

5. 임베딩 품질 정량 평가
   $ python codes/embedding/quality_eval.py

6. 평가 리포트 저장
   $ python codes/embedding/quality_eval.py --json-output /workspace/eval_report.json
```

### 결과 해석 가이드

**search_test.py 출력 확인:**
- top-1 결과가 질의 의도와 맞는지 육안 확인
- Dense와 Hybrid 일치율이 50% 이상이면 일관성 양호
- 필터 적용 시 결과가 해당 카테고리로 한정되는지 확인

**quality_eval.py 출력 확인:**
- 판별력 등급이 "양호" 이상이면 다음 단계 진행 가능
- chunk_type별 성능에서 hyde가 자연어 질문에 가장 높으면 정상
- summary가 넓은 주제에서 가장 높으면 정상
- 비유사 쌍의 overlap이 20% 이하면 양호

### 문제 발견 시 대응

| 증상 | 가능한 원인 | 대응 |
|---|---|---|
| 검색 결과가 질의와 무관 | 임베딩 모델 한국어 성능 부족 | 다른 Korean 임베딩 모델 비교 |
| 판별력이 "개선 필요" | 청크 텍스트가 너무 짧거나 일반적 | chunker.py 청크 전략 재검토 |
| hyde가 다른 타입보다 항상 낮음 | HyDE 질문 생성 품질 문제 | v2 문서의 HyDE 섹션 점검 |
| 필터 결과가 0건 | 해당 태그가 색인에 없음 | 태그 분포 확인 후 질의 수정 |
| Hybrid가 Dense보다 항상 안 좋음 | Sparse 벡터 미색인 | upserter.py에서 sparse 색인 여부 확인 |
