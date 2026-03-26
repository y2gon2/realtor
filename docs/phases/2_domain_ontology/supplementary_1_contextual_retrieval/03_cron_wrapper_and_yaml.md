# Cron 래퍼 스크립트 및 YAML 태스크 정의

> 목적: `contextual_prefix.py`를 cron으로 주기 실행하기 위한 래퍼 스크립트와 태스크 설정

---

## 1. `codes/cron/contextual_prefix_cron.sh`

`enrich_aliases_cron.sh`와 동일한 구조. Lock 관리 + 로그 + Python 스크립트 `--once` 호출.

```bash
#!/bin/bash
# =============================================================================
# Contextual Retrieval 맥락 prefix 생성 Cron 래퍼 스크립트
#
# 4분마다 1배치씩 처리 (온톨로지 15개 또는 법률문서 8개).
# 체크포인트 기반으로 이전에 처리한 배치는 건너뜀.
#
# 사용법:
#   ./contextual_prefix_cron.sh contextual_prefix   (manage_cron.sh 호환)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="/home/gon/ws/rag"
LOG_DIR="${SCRIPT_DIR}/logs"
LOCK_FILE="/tmp/claude_cron_locks/contextual_prefix.lock"

export HOME="/home/gon"
# Claude Code 중첩 세션 방지 (cron 환경에서 필수)
unset CLAUDECODE 2>/dev/null || true

mkdir -p "${LOG_DIR}" "$(dirname "${LOCK_FILE}")"

LOG_FILE="${LOG_DIR}/contextual_prefix_$(date '+%Y%m%d').log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "${LOG_FILE}"
}

# --- 락 관리 ---
if [ -f "${LOCK_FILE}" ]; then
    pid=$(cat "${LOCK_FILE}" 2>/dev/null)
    if kill -0 "${pid}" 2>/dev/null; then
        log "[SKIP] 이전 작업 진행 중 (PID: ${pid})"
        exit 0
    fi
    rm -f "${LOCK_FILE}"
fi
echo $$ > "${LOCK_FILE}"
trap 'rm -f "${LOCK_FILE}"' EXIT

# --- 실행 ---
log "[START] contextual_prefix --once 실행 (Claude Code CLI 모드)"

output=$(python3 "${PROJECT_ROOT}/scripts/contextual_prefix.py" --once 2>&1) || {
    log "[ERROR] 실행 실패: ${output}"
    exit 1
}

log "${output}"

# 완료 체크 (모든 배치 처리 완료 시)
if echo "${output}" | grep -q "모든 배치 처리 완료"; then
    log "[DONE] 전체 contextual prefix 생성 완료!"
fi
```

---

## 2. `codes/cron/config/claude_tasks.yaml` 추가 내용

기존 파일의 `tasks:` 섹션 하단에 추가:

```yaml
  # Task 5: Contextual Retrieval 맥락 prefix 생성
  contextual_prefix:
    enabled: true
    description: "온톨로지+법률문서 contextual prefix 생성 (배치 1개/4분, Sonnet)"
    schedule: "*/4 20-23,0-8 * * *"     # 매 4분마다 (20시~08시)
    script_override: "contextual_prefix_cron.sh"
    # 아래 필드는 manage_cron.sh 호환을 위해 유지 (script_override 시 직접 사용 안 함)
    source_dir: "ontology_data/entries"
    output_dir: "ontology_data/contextual_prefixes"
    reject_dir: "ontology_data/contextual_prefixes"
    retry:
      max_attempts: 3
      wait_seconds: 60
```

### 스케줄 설명

```
*/4 20-23,0-8 * * *
│   │
│   └─ 20시~23시, 0시~8시 (야간/새벽 시간대)
└───── 매 4분마다

# 이유:
# - 낮 시간(9시~19시)에는 실시간 서비스용 API 할당량 확보
# - 4분 간격: Claude CLI 호출 1회(~60초) + 여유(3분)로 겹침 방지
# - 170 배치 × 4분 = ~680분 ≈ 약 11.3시간
# - 야간 12시간 윈도우 내에 완료 가능
```

---

## 3. `manage_cron.sh`와의 호환성

`manage_cron.sh`는 `script_override` 필드가 있으면 해당 스크립트를 직접 실행하고, `claude_preprocess.sh`를 건너뛴다.

```bash
# manage_cron.sh의 관련 로직 (기존 코드):
if [ -n "${script_override}" ]; then
    cron_cmd="${SCRIPT_DIR}/${script_override} ${task_name}"
else
    cron_cmd="${SCRIPT_DIR}/claude_preprocess.sh ${task_name}"
fi
```

따라서 `contextual_prefix_cron.sh`를 `codes/cron/` 디렉토리에 배치하면 자동으로 인식됨.

### Cron 등록/해제

```bash
# 등록
cd /home/gon/ws/rag/codes/cron
./manage_cron.sh install

# 상태 확인
./manage_cron.sh status

# 해제
./manage_cron.sh remove
```

---

## 4. 로그 확인

```bash
# 오늘 로그
tail -f /home/gon/ws/rag/codes/cron/logs/contextual_prefix_$(date '+%Y%m%d').log

# 진행률 확인
python3 /home/gon/ws/rag/scripts/contextual_prefix.py --status
```

### 예상 로그 출력

```
[2026-03-27 20:00:02] [START] contextual_prefix --once 실행 (Claude Code CLI 모드)
[2026-03-27 20:00:45] [1/170] onto_tax_0000 처리 중 (ontology)...
  → 15개 prefix 생성
  진행률: 1/170 (0%)
[2026-03-27 20:04:02] [START] contextual_prefix --once 실행 (Claude Code CLI 모드)
[2026-03-27 20:04:38] [2/170] onto_tax_0001 처리 중 (ontology)...
  → 15개 prefix 생성
  진행률: 2/170 (1%)
...
[2026-03-28 07:12:15] [완료] 모든 배치 처리 완료 (170/170)
[2026-03-28 07:12:15] [DONE] 전체 contextual prefix 생성 완료!
```
