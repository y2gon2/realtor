#!/usr/bin/env python3
"""
Opus 4.6 베이스라인 테스트: RAG 없이 순수 LLM 답변 품질 측정

test_set_v1.md의 질문을 Claude Code CLI (Opus 4.6)로 실행하고
결과를 opus_result/ 폴더에 마크다운으로 저장.

Usage:
    python opus_baseline_test.py --parts a,c,d
    python opus_baseline_test.py --parts b --resume
    python opus_baseline_test.py --parts a,b,c,d
"""

import argparse
import json
import logging
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Paths ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
TEST_SET_PATH = BASE_DIR / "data" / "test_set_v1.md"
OUTPUT_DIR = BASE_DIR / "opus_result"
CHECKPOINT_PATH = OUTPUT_DIR / "checkpoint.json"
LOG_PATH = OUTPUT_DIR / "run.log"

SYSTEM_PROMPT = "당신은 대한민국 부동산 전문 상담사입니다. 한국어로 답변하세요. 구체적이고 실용적으로 답변하세요."
MODEL = "claude-opus-4-6"
COOLDOWN = 30  # seconds between questions
CLI_TIMEOUT = 300  # seconds

# Opus 4.6 API pricing for cost estimation
PRICE_INPUT_PER_M = 15.0   # $/1M input tokens
PRICE_OUTPUT_PER_M = 75.0  # $/1M output tokens

# Follow-up suggestion detection patterns
FOLLOWUP_PATTERNS = [
    r"해\s*드릴까요",
    r"알려\s*드릴까요",
    r"설명\s*드릴까요",
    r"안내\s*드릴까요",
    r"확인해\s*보시겠",
    r"진행할까요",
    r"도움이\s*될까요",
    r"궁금하신\s*점",
    r"더\s*궁금",
    r"질문.*있으시면",
    r"말씀해\s*주세요",
    r"알아볼까요",
]

# ── Data Classes ───────────────────────────────────────────────────────

@dataclass
class Question:
    part: str
    set_id: Optional[str]
    set_title: Optional[str]
    q_num: int          # 1-based within section/set
    text: str
    global_id: str = "" # e.g., "A-042", "B-003-Q5", "D-007-Q3"

@dataclass
class QuestionSet:
    set_id: str         # e.g., "B-001", "D-013"
    title: str
    questions: list = field(default_factory=list)

@dataclass
class Result:
    question_id: str
    question_text: str
    answer: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    elapsed_ms: int = 0
    cost_usd: float = 0.0
    estimated_api_cost: float = 0.0
    followup_detected: bool = False
    followup_accepted: bool = False
    followup_answer: str = ""
    followup_input_tokens: int = 0
    followup_output_tokens: int = 0
    followup_elapsed_ms: int = 0
    followup_cost_usd: float = 0.0
    context_turns: int = 0
    error: str = ""

# ── Parser ─────────────────────────────────────────────────────────────

def parse_test_set(path: Path) -> dict:
    """Parse test_set_v1.md into structured parts."""
    text = path.read_text(encoding="utf-8")
    parts = {"a": [], "b": [], "c": [], "d": []}

    # Split into major sections
    sections = re.split(r"^## (Part [A-D]:.+)$", text, flags=re.MULTILINE)

    for i in range(1, len(sections), 2):
        header = sections[i].strip()
        body = sections[i + 1]

        if "Part A:" in header:
            parts["a"] = _parse_singles(body, "A")
        elif "Part B:" in header:
            parts["b"] = _parse_sets(body, "B")
        elif "Part C:" in header:
            parts["c"] = _parse_singles_c(body, "C")
        elif "Part D:" in header:
            parts["d"] = _parse_sets(body, "D")

    return parts


def _parse_singles(body: str, part: str) -> list:
    """Parse Part A single questions (numbered 1-100)."""
    questions = []
    # Split by subsections (### A-1. 매매/시세 ...)
    subsections = re.split(r"^### [A-Z]-\d+\..+$", body, flags=re.MULTILINE)
    full_body = "\n".join(subsections)

    for m in re.finditer(r"^(\d+)\.\s+(.+)$", full_body, flags=re.MULTILINE):
        num = int(m.group(1))
        text = m.group(2).strip()
        q = Question(
            part=part,
            set_id=None,
            set_title=None,
            q_num=num,
            text=text,
            global_id=f"A-{num:03d}",
        )
        questions.append(q)
    return questions


def _parse_singles_c(body: str, part: str) -> list:
    """Parse Part C single questions (numbered 101-112)."""
    questions = []
    for m in re.finditer(r"^(\d+)\.\s+(.+)$", body, flags=re.MULTILINE):
        num = int(m.group(1))
        text = m.group(2).strip()
        q = Question(
            part=part,
            set_id=None,
            set_title=None,
            q_num=num,
            text=text,
            global_id=f"C-{num:03d}",
        )
        questions.append(q)
    return questions


def _parse_sets(body: str, part: str) -> list:
    """Parse Part B or D question sets."""
    sets = []
    # Split by set headers: ### B-001. title (N개) or ### D-001. title (N개)
    pattern = rf"^### ({part}-\d{{3}})\.\s+(.+?)\s*\(\d+개\)\s*$"
    headers = list(re.finditer(pattern, body, flags=re.MULTILINE))

    for idx, hm in enumerate(headers):
        set_id = hm.group(1)
        title = hm.group(2).strip()
        start = hm.end()
        end = headers[idx + 1].start() if idx + 1 < len(headers) else len(body)
        set_body = body[start:end]

        qs = QuestionSet(set_id=set_id, title=title)
        for qm in re.finditer(r"^(\d+)\.\s+(.+)$", set_body, flags=re.MULTILINE):
            q_num = int(qm.group(1))
            q = Question(
                part=part,
                set_id=set_id,
                set_title=title,
                q_num=q_num,
                text=qm.group(2).strip(),
                global_id=f"{set_id}-Q{q_num}",
            )
            qs.questions.append(q)
        if qs.questions:
            sets.append(qs)
    return sets


# ── CLI Caller ─────────────────────────────────────────────────────────

def call_claude_cli(prompt: str, system_prompt: str = SYSTEM_PROMPT,
                    timeout: int = CLI_TIMEOUT) -> dict:
    """Call Claude Code CLI and return parsed result."""
    cmd = [
        "claude", "-p", prompt,
        "--model", MODEL,
        "--output-format", "json",
        "--system-prompt", system_prompt,
    ]
    start = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed_ms = int((time.time() - start) * 1000)

        if proc.returncode != 0:
            return {
                "answer": "",
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_tokens": 0,
                "cache_read_tokens": 0,
                "elapsed_ms": elapsed_ms,
                "cost_usd": 0.0,
                "error": f"CLI exit code {proc.returncode}: {proc.stderr[:500]}",
            }

        data = json.loads(proc.stdout)
        usage = data.get("usage", {})
        return {
            "answer": data.get("result", ""),
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "cache_creation_tokens": usage.get("cache_creation_input_tokens", 0),
            "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
            "elapsed_ms": elapsed_ms,
            "cost_usd": data.get("total_cost_usd", 0.0),
            "error": "",
        }
    except subprocess.TimeoutExpired:
        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "answer": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "elapsed_ms": elapsed_ms,
            "cost_usd": 0.0,
            "error": f"Timeout after {timeout}s",
        }
    except json.JSONDecodeError as e:
        elapsed_ms = int((time.time() - start) * 1000)
        return {
            "answer": "",
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "elapsed_ms": elapsed_ms,
            "cost_usd": 0.0,
            "error": f"JSON parse error: {e}",
        }


def estimate_api_cost(input_tokens: int, output_tokens: int) -> float:
    """Estimate API cost based on Opus 4.6 pricing."""
    return (input_tokens * PRICE_INPUT_PER_M + output_tokens * PRICE_OUTPUT_PER_M) / 1_000_000


# ── Follow-up Detection ───────────────────────────────────────────────

def has_followup_suggestion(text: str) -> bool:
    """Check if response ends with a follow-up suggestion."""
    # Check last 200 chars for suggestion patterns
    tail = text[-200:] if len(text) > 200 else text
    for pat in FOLLOWUP_PATTERNS:
        if re.search(pat, tail):
            return True
    return False


# ── Checkpoint / Progress ─────────────────────────────────────────────

class ProgressTracker:
    def __init__(self, path: Path):
        self.path = path
        self.data = {"completed": {}, "started_at": None}
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))

    def is_completed(self, qid: str) -> bool:
        return qid in self.data["completed"]

    def mark_completed(self, qid: str, result: Result):
        self.data["completed"][qid] = {
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "elapsed_ms": result.elapsed_ms,
            "cost_usd": result.cost_usd,
            "estimated_api_cost": result.estimated_api_cost,
            "followup_detected": result.followup_detected,
            "followup_accepted": result.followup_accepted,
            "error": result.error,
        }
        self._save()

    def set_started(self):
        if not self.data.get("started_at"):
            self.data["started_at"] = datetime.now().isoformat()
            self._save()

    def _save(self):
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_completed_count(self) -> int:
        return len(self.data["completed"])

    def get_stats(self) -> dict:
        completed = self.data["completed"]
        if not completed:
            return {}
        total_input = sum(v["input_tokens"] for v in completed.values())
        total_output = sum(v["output_tokens"] for v in completed.values())
        total_cost = sum(v["cost_usd"] for v in completed.values())
        total_api_cost = sum(v["estimated_api_cost"] for v in completed.values())
        total_elapsed = sum(v["elapsed_ms"] for v in completed.values())
        errors = sum(1 for v in completed.values() if v["error"])
        followups = sum(1 for v in completed.values() if v["followup_accepted"])
        return {
            "count": len(completed),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cost_usd": total_cost,
            "total_api_cost_usd": total_api_cost,
            "total_elapsed_ms": total_elapsed,
            "avg_elapsed_ms": total_elapsed // max(len(completed), 1),
            "errors": errors,
            "followups_accepted": followups,
        }


# ── Result Writer ─────────────────────────────────────────────────────

class ResultWriter:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write_singles(self, part_label: str, results: list, filename: str,
                      timestamp: str):
        """Write single-question results file."""
        path = self.output_dir / filename
        lines = []
        lines.append(f"# Part {part_label} 단일 질문 Opus 4.6 테스트 결과\n")
        lines.append(f"실행 시각: {timestamp}")
        lines.append(f"총 질문 수: {len(results)}\n")
        lines.append("---\n")

        for r in results:
            lines.append(self._format_result(r))

        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def write_multiturn_set(self, set_id: str, title: str, results: list,
                            timestamp: str):
        """Write a multi-turn set result file."""
        filename = f"part_{set_id[0].lower()}_{set_id.split('-')[1]}.md"
        path = self.output_dir / filename
        lines = []
        lines.append(f"# {set_id}. {title} Opus 4.6 테스트 결과\n")
        lines.append(f"실행 시각: {timestamp}")
        lines.append(f"질문 수: {len(results)}\n")
        lines.append("---\n")

        for r in results:
            lines.append(self._format_result(r, multiturn=True))

        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _format_result(self, r: Result, multiturn: bool = False) -> str:
        lines = []
        lines.append(f"### Q{r.question_id.split('-')[-1].replace('Q', '').replace('q', '')}. {r.question_text}\n")

        meta_parts = [
            f"**입력 토큰**: {r.input_tokens:,}",
            f"**출력 토큰**: {r.output_tokens:,}",
            f"**소요시간**: {r.elapsed_ms:,}ms",
            f"**CLI 비용**: ${r.cost_usd:.4f}",
            f"**추정 API 비용**: ${r.estimated_api_cost:.4f}",
        ]
        lines.append(" | ".join(meta_parts))

        if multiturn:
            ctx = f"**대화 컨텍스트**: {r.context_turns}턴 누적"
            fu = "감지됨" if r.followup_detected else "미감지"
            lines.append(f"{ctx} | **후속 제안**: {fu}")

        if r.error:
            lines.append(f"\n**오류**: {r.error}\n")
        else:
            lines.append(f"\n**답변:**\n\n{r.answer}\n")

        if r.followup_accepted and r.followup_answer:
            lines.append(f"**후속 답변** (자동 수락):\n\n{r.followup_answer}\n")

        lines.append("---")
        return "\n".join(lines)


# ── Runners ────────────────────────────────────────────────────────────

def run_single_question(q: Question, tracker: ProgressTracker,
                        logger: logging.Logger) -> Optional[Result]:
    """Run a single question through CLI."""
    if tracker.is_completed(q.global_id):
        logger.info(f"[SKIP] {q.global_id} already completed")
        return None

    logger.info(f"[RUN] {q.global_id}: {q.text[:60]}...")

    resp = call_claude_cli(q.text)

    # Retry once on error
    if resp["error"]:
        logger.warning(f"[RETRY] {q.global_id}: {resp['error']}")
        time.sleep(60)
        resp = call_claude_cli(q.text)

    result = Result(
        question_id=q.global_id,
        question_text=q.text,
        answer=resp["answer"],
        input_tokens=resp["input_tokens"],
        output_tokens=resp["output_tokens"],
        cache_creation_tokens=resp["cache_creation_tokens"],
        cache_read_tokens=resp["cache_read_tokens"],
        elapsed_ms=resp["elapsed_ms"],
        cost_usd=resp["cost_usd"],
        estimated_api_cost=estimate_api_cost(resp["input_tokens"], resp["output_tokens"]),
        error=resp["error"],
    )

    # Follow-up detection
    if not resp["error"] and has_followup_suggestion(resp["answer"]):
        result.followup_detected = True
        logger.info(f"[FOLLOWUP] {q.global_id}: suggestion detected, accepting...")
        time.sleep(COOLDOWN)
        fu_prompt = f"이전 질문: {q.text}\n이전 답변 요약: (위 답변 참조)\n\n네, 그렇게 해주세요. 자세히 알려주세요."
        fu_resp = call_claude_cli(fu_prompt)
        if not fu_resp["error"]:
            result.followup_accepted = True
            result.followup_answer = fu_resp["answer"]
            result.followup_input_tokens = fu_resp["input_tokens"]
            result.followup_output_tokens = fu_resp["output_tokens"]
            result.followup_elapsed_ms = fu_resp["elapsed_ms"]
            result.followup_cost_usd = fu_resp["cost_usd"]

    tracker.mark_completed(q.global_id, result)
    logger.info(
        f"[DONE] {q.global_id}: "
        f"tokens={resp['input_tokens']}+{resp['output_tokens']} "
        f"time={resp['elapsed_ms']}ms cost=${resp['cost_usd']:.4f}"
    )
    return result


def run_multiturn_set(qs: QuestionSet, tracker: ProgressTracker,
                      logger: logging.Logger) -> list:
    """Run a multi-turn question set."""
    results = []
    history = []  # list of {"question": str, "answer": str}

    # Check if entire set is already done
    all_done = all(
        tracker.is_completed(q.global_id) for q in qs.questions
    )
    if all_done:
        logger.info(f"[SKIP SET] {qs.set_id} already completed")
        return results

    logger.info(f"[SET START] {qs.set_id}: {qs.title} ({len(qs.questions)}개)")

    for q in qs.questions:
        if tracker.is_completed(q.global_id):
            # Reconstruct history from checkpoint (answer not stored, skip)
            logger.info(f"[SKIP] {q.global_id} already completed")
            # We can't reconstruct the answer from checkpoint, so reset history
            # This means resume mid-set loses context, which is acceptable
            history = []
            continue

        # Build prompt with conversation context
        if history:
            prompt = _build_multiturn_prompt(history, q.text)
        else:
            prompt = q.text

        logger.info(f"[RUN] {q.global_id}: {q.text[:60]}... (context: {len(history)} turns)")

        resp = call_claude_cli(prompt)

        # Retry once on error
        if resp["error"]:
            logger.warning(f"[RETRY] {q.global_id}: {resp['error']}")
            time.sleep(60)
            resp = call_claude_cli(prompt)

        result = Result(
            question_id=q.global_id,
            question_text=q.text,
            answer=resp["answer"],
            input_tokens=resp["input_tokens"],
            output_tokens=resp["output_tokens"],
            cache_creation_tokens=resp["cache_creation_tokens"],
            cache_read_tokens=resp["cache_read_tokens"],
            elapsed_ms=resp["elapsed_ms"],
            cost_usd=resp["cost_usd"],
            estimated_api_cost=estimate_api_cost(resp["input_tokens"], resp["output_tokens"]),
            context_turns=len(history),
            error=resp["error"],
        )

        # Follow-up detection for last question in set only
        if not resp["error"] and has_followup_suggestion(resp["answer"]):
            result.followup_detected = True
            # Accept follow-up if intent seems aligned
            logger.info(f"[FOLLOWUP] {q.global_id}: suggestion detected, accepting...")
            time.sleep(COOLDOWN)
            fu_history = history + [{"question": q.text, "answer": resp["answer"]}]
            fu_prompt = _build_multiturn_prompt(fu_history, "네, 그렇게 해주세요. 자세히 알려주세요.")
            fu_resp = call_claude_cli(fu_prompt)
            if not fu_resp["error"]:
                result.followup_accepted = True
                result.followup_answer = fu_resp["answer"]
                result.followup_input_tokens = fu_resp["input_tokens"]
                result.followup_output_tokens = fu_resp["output_tokens"]
                result.followup_elapsed_ms = fu_resp["elapsed_ms"]
                result.followup_cost_usd = fu_resp["cost_usd"]

        # Update history
        if not resp["error"]:
            history.append({"question": q.text, "answer": resp["answer"]})

        tracker.mark_completed(q.global_id, result)
        results.append(result)
        logger.info(
            f"[DONE] {q.global_id}: "
            f"tokens={resp['input_tokens']}+{resp['output_tokens']} "
            f"time={resp['elapsed_ms']}ms"
        )

        # Cooldown (skip after last question)
        if q != qs.questions[-1]:
            time.sleep(COOLDOWN)

    logger.info(f"[SET DONE] {qs.set_id}")
    return results


def _build_multiturn_prompt(history: list, current_question: str) -> str:
    """Build a prompt that includes conversation history."""
    parts = ["다음은 이전 대화 내용입니다:\n"]
    for turn in history:
        parts.append(f"사용자: {turn['question']}")
        parts.append(f"상담사: {turn['answer']}\n")
    parts.append(f"위 대화에 이어서 다음 질문에 답변해주세요:\n사용자: {current_question}")
    return "\n".join(parts)


# ── Summary Generator ──────────────────────────────────────────────────

def generate_summary(tracker: ProgressTracker, start_time: str,
                     output_dir: Path):
    """Generate summary.md with statistics."""
    stats = tracker.get_stats()
    if not stats:
        return

    completed = tracker.data["completed"]

    # Per-part stats
    part_stats = {}
    for qid, data in completed.items():
        if qid.startswith("A-"):
            part = "A"
        elif qid.startswith("B-"):
            part = "B"
        elif qid.startswith("C-"):
            part = "C"
        elif qid.startswith("D-"):
            part = "D"
        else:
            part = "?"

        if part not in part_stats:
            part_stats[part] = {
                "count": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
                "api_cost_usd": 0.0,
                "elapsed_ms": 0,
                "errors": 0,
                "followups": 0,
            }
        ps = part_stats[part]
        ps["count"] += 1
        ps["input_tokens"] += data["input_tokens"]
        ps["output_tokens"] += data["output_tokens"]
        ps["cost_usd"] += data["cost_usd"]
        ps["api_cost_usd"] += data["estimated_api_cost"]
        ps["elapsed_ms"] += data["elapsed_ms"]
        if data["error"]:
            ps["errors"] += 1
        if data.get("followup_accepted"):
            ps["followups"] += 1

    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = []
    lines.append("# Opus 4.6 베이스라인 테스트 결과 요약\n")
    lines.append(f"실행 일시: {start_time} ~ {end_time}")
    lines.append(f"모델: {MODEL}")
    lines.append(f"설정: cooldown={COOLDOWN}초, timeout={CLI_TIMEOUT}초")
    lines.append(f"시스템 프롬프트: \"{SYSTEM_PROMPT}\"\n")
    lines.append("---\n")

    # Overall stats
    lines.append("## 전체 통계\n")
    lines.append("| 항목 | 값 |")
    lines.append("|------|------|")
    lines.append(f"| 총 질문 수 | {stats['count']}개 |")
    lines.append(f"| 오류 | {stats['errors']}개 |")
    lines.append(f"| 후속 제안 수락 | {stats['followups_accepted']}건 |")
    lines.append(f"| 총 입력 토큰 | {stats['total_input_tokens']:,} |")
    lines.append(f"| 총 출력 토큰 | {stats['total_output_tokens']:,} |")
    lines.append(f"| 평균 소요시간 | {stats['avg_elapsed_ms']:,}ms |")
    lines.append(f"| 총 CLI 비용 | ${stats['total_cost_usd']:.2f} |")
    lines.append(f"| 총 추정 API 비용 | ${stats['total_api_cost_usd']:.2f} |")
    lines.append(f"| 총 실행시간 | {stats['total_elapsed_ms'] // 60000}분 |")
    lines.append("")

    # Per-part stats
    lines.append("---\n")
    lines.append("## Part별 통계\n")
    for part_name in sorted(part_stats.keys()):
        ps = part_stats[part_name]
        avg_ms = ps["elapsed_ms"] // max(ps["count"], 1)
        lines.append(f"### Part {part_name}")
        lines.append("| 항목 | 값 |")
        lines.append("|------|----|")
        lines.append(f"| 질문 수 | {ps['count']}개 |")
        lines.append(f"| 오류 | {ps['errors']}개 |")
        lines.append(f"| 후속 수락 | {ps['followups']}건 |")
        lines.append(f"| 입력 토큰 | {ps['input_tokens']:,} |")
        lines.append(f"| 출력 토큰 | {ps['output_tokens']:,} |")
        lines.append(f"| 평균 소요시간 | {avg_ms:,}ms |")
        lines.append(f"| CLI 비용 | ${ps['cost_usd']:.2f} |")
        lines.append(f"| 추정 API 비용 | ${ps['api_cost_usd']:.2f} |")
        lines.append("")

    # Cost comparison
    lines.append("---\n")
    lines.append("## 비용 비교 (API 기준 추산)\n")
    lines.append("| 항목 | Opus 4.6 | 비고 |")
    lines.append("|------|----------|------|")
    lines.append(f"| 입력 토큰 단가 | $15/1M | |")
    lines.append(f"| 출력 토큰 단가 | $75/1M | |")
    lines.append(f"| 총 입력 토큰 | {stats['total_input_tokens']:,} | |")
    lines.append(f"| 총 출력 토큰 | {stats['total_output_tokens']:,} | |")
    lines.append(f"| 추정 API 비용 | ${stats['total_api_cost_usd']:.2f} | |")
    q_count = max(stats["count"], 1)
    lines.append(f"| 질문당 평균 비용 | ${stats['total_api_cost_usd'] / q_count:.4f} | |")
    lines.append("")

    # File list
    lines.append("---\n")
    lines.append("## 결과 파일 목록\n")
    lines.append("| 파일 | 내용 |")
    lines.append("|------|------|")
    for f in sorted(output_dir.glob("part_*.md")):
        lines.append(f"| {f.name} | {f.stem} 결과 |")
    lines.append("| checkpoint.json | 진행 상태 |")
    lines.append("| run.log | 실행 로그 |")
    lines.append("| summary.md | 본 요약 문서 |")

    summary_path = output_dir / "summary.md"
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    return summary_path


# ── Main ───────────────────────────────────────────────────────────────

def setup_logging(log_path: Path) -> logging.Logger:
    logger = logging.getLogger("opus_test")
    logger.setLevel(logging.INFO)
    # File handler
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(fh)
    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(ch)
    return logger


def main():
    parser = argparse.ArgumentParser(description="Opus 4.6 baseline test")
    parser.add_argument("--parts", default="a,b,c,d",
                        help="Parts to run (comma-separated: a,b,c,d)")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from checkpoint")
    args = parser.parse_args()

    parts_to_run = [p.strip().lower() for p in args.parts.split(",")]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logger = setup_logging(LOG_PATH)
    tracker = ProgressTracker(CHECKPOINT_PATH)
    writer = ResultWriter(OUTPUT_DIR)

    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tracker.set_started()

    # Graceful shutdown
    shutdown_requested = False
    def signal_handler(sig, frame):
        nonlocal shutdown_requested
        if shutdown_requested:
            logger.warning("[FORCE EXIT]")
            sys.exit(1)
        shutdown_requested = True
        logger.warning("[SHUTDOWN] Saving checkpoint and exiting...")

    signal.signal(signal.SIGINT, signal_handler)

    # Parse test set
    logger.info(f"[PARSE] Loading test set from {TEST_SET_PATH}")
    test_set = parse_test_set(TEST_SET_PATH)
    total_q = (
        len(test_set["a"]) +
        sum(len(s.questions) for s in test_set["b"]) +
        len(test_set["c"]) +
        sum(len(s.questions) for s in test_set["d"])
    )
    logger.info(
        f"[PARSE] Loaded: A={len(test_set['a'])}, "
        f"B={len(test_set['b'])} sets/"
        f"{sum(len(s.questions) for s in test_set['b'])}q, "
        f"C={len(test_set['c'])}, "
        f"D={len(test_set['d'])} sets/"
        f"{sum(len(s.questions) for s in test_set['d'])}q, "
        f"Total={total_q}"
    )

    # ── Run Part C first (small, for validation) ──
    if "c" in parts_to_run and not shutdown_requested:
        logger.info("[PART C] Starting 12 single questions...")
        c_results = []
        for q in test_set["c"]:
            if shutdown_requested:
                break
            r = run_single_question(q, tracker, logger)
            if r:
                c_results.append(r)
            time.sleep(COOLDOWN)
        if c_results:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            writer.write_singles("C", c_results, "part_c_singles.md", ts)
            logger.info(f"[PART C] Done: {len(c_results)} questions")

    # ── Run Part A ──
    if "a" in parts_to_run and not shutdown_requested:
        logger.info("[PART A] Starting 100 single questions...")
        a_results = []
        for q in test_set["a"]:
            if shutdown_requested:
                break
            r = run_single_question(q, tracker, logger)
            if r:
                a_results.append(r)
            time.sleep(COOLDOWN)
        if a_results:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            writer.write_singles("A", a_results, "part_a_singles.md", ts)
            logger.info(f"[PART A] Done: {len(a_results)} questions")

    # ── Run Part D ──
    if "d" in parts_to_run and not shutdown_requested:
        logger.info(f"[PART D] Starting {len(test_set['d'])} sets...")
        for qs in test_set["d"]:
            if shutdown_requested:
                break
            d_results = run_multiturn_set(qs, tracker, logger)
            if d_results:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                writer.write_multiturn_set(qs.set_id, qs.title, d_results, ts)
            time.sleep(COOLDOWN)
        logger.info("[PART D] Done")

    # ── Run Part B ──
    if "b" in parts_to_run and not shutdown_requested:
        logger.info(f"[PART B] Starting {len(test_set['b'])} sets...")
        for qs in test_set["b"]:
            if shutdown_requested:
                break
            b_results = run_multiturn_set(qs, tracker, logger)
            if b_results:
                ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                writer.write_multiturn_set(qs.set_id, qs.title, b_results, ts)
            time.sleep(COOLDOWN)
        logger.info("[PART B] Done")

    # ── Generate Summary ──
    logger.info("[SUMMARY] Generating summary.md...")
    generate_summary(tracker, start_time, OUTPUT_DIR)
    logger.info("[COMPLETE] All done.")


if __name__ == "__main__":
    main()
