"""Streamlit presentation demo for Day 14 AI Đánh giá.

The app reads repository artifacts only. It does not create benchmark scores
or expose expected answers to the system under evaluation.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

load_dotenv(REPO_ROOT / ".env")

GOLDEN_PATH = REPO_ROOT / "golden_dataset.json"
ACTUAL_PATH = REPO_ROOT / "artifacts" / "actual_answers.json"
BENCHMARK_PATH = REPO_ROOT / "artifacts" / "benchmark_results.json"
FIVE_WHYS_PATH = REPO_ROOT / "artifacts" / "five_whys.md"
REFLECTION_PATH = REPO_ROOT / "reflection.md"
CORPUS_DIR = REPO_ROOT / "data" / "technology_store"

METRIC_LABELS = {
    "context_recall": ("Context Recall", "Retriever lấy được bao nhiêu evidence cần thiết?"),
    "context_precision": (
        "Context Precision",
        "Evidence hữu ích có được xếp trước context nhiễu không?",
    ),
    "faithfulness": ("Faithfulness", "Câu trả lời có được support bởi retrieved context không?"),
    "relevance": ("Relevance", "Câu trả lời có đúng trọng tâm câu hỏi không?"),
    "completeness": ("Completeness", "Câu trả lời có đủ các ý quan trọng không?"),
}

PRESENTATION_STEPS = [
    "Vấn đề",
    "Golden Dataset",
    "Chạy RAG",
    "Đánh giá",
    "Chẩn đoán",
    "5 Whys",
    "Regression",
    "Kết luận",
]


@st.cache_data(show_spinner=False)
def read_json(path: Path, modified_at: float | None) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"_error": f"JSON không hợp lệ: {path.name}"}
    return value if isinstance(value, dict) else {"_error": f"{path.name} không phải JSON object"}


@st.cache_data(show_spinner=False)
def read_reflection(path: Path, modified_at: float | None) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


@st.cache_data(show_spinner=False)
def read_markdown(path: Path, modified_at: float | None) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def file_modified_at(path: Path) -> float | None:
    return path.stat().st_mtime if path.exists() else None


def qa_records(golden: dict[str, Any] | None) -> list[dict[str, Any]]:
    records = (golden or {}).get("qa_pairs", [])
    return records if isinstance(records, list) else []


def answers_by_id(actual: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    records = (actual or {}).get("answers", [])
    if not isinstance(records, list):
        return {}
    return {
        str(item.get("id")): item
        for item in records
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def results_by_id(benchmark: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    records = (benchmark or {}).get("results", [])
    if not isinstance(records, list):
        return {}
    return {
        str(item.get("id")): item
        for item in records
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def artifact_consistency(
    cases: list[dict[str, Any]],
    actual_lookup: dict[str, dict[str, Any]],
    result_lookup: dict[str, dict[str, Any]],
) -> tuple[bool, list[str]]:
    """Check that saved artifacts belong to the current golden dataset."""

    problems: list[str] = []
    for case in cases:
        case_id = str(case.get("id", ""))
        question = str(case.get("question", "")).strip()
        actual = actual_lookup.get(case_id)
        result = result_lookup.get(case_id)
        if actual is None:
            problems.append(f"{case_id}: thiếu actual answer")
            continue
        if str(actual.get("question", "")).strip() != question:
            problems.append(f"{case_id}: actual answer không khớp câu hỏi trong golden dataset")
        if result is None:
            problems.append(f"{case_id}: thiếu benchmark result")
    extra_actual = sorted(set(actual_lookup) - {str(case.get("id", "")) for case in cases})
    extra_results = sorted(set(result_lookup) - {str(case.get("id", "")) for case in cases})
    if extra_actual:
        problems.append("actual_answers có ID lạ: " + ", ".join(extra_actual))
    if extra_results:
        problems.append("benchmark_results có ID lạ: " + ", ".join(extra_results))
    return not problems, problems


def is_filled_case(case: dict[str, Any]) -> bool:
    return bool(str(case.get("question", "")).strip()) and bool(
        str(case.get("expected_answer", "")).strip()
    )


def score_value(value: Any) -> float | None:
    return value if isinstance(value, (int, float)) else None


def format_score(value: Any) -> str:
    numeric = score_value(value)
    return "n/a" if numeric is None else f"{numeric:.3f}"


def metric_bar(metric_key: str, result: dict[str, Any] | None) -> None:
    label, help_text = METRIC_LABELS[metric_key]
    value = score_value((result or {}).get(metric_key))
    st.caption(help_text)
    if value is None:
        st.info(f"{label}: benchmark artifact has no score yet.")
        return
    st.metric(label, f"{value:.3f}")
    st.progress(max(0.0, min(1.0, value)))


def result_scores(result: dict[str, Any] | None) -> dict[str, float | None]:
    return {key: score_value((result or {}).get(key)) for key in METRIC_LABELS}


def threshold_status(
    scores: dict[str, float | None],
    thresholds: dict[str, float],
) -> tuple[bool, list[str]]:
    failed: list[str] = []
    for key, threshold in thresholds.items():
        value = scores.get(key)
        if value is None:
            failed.append(f"{METRIC_LABELS[key][0]} chưa có điểm")
        elif value < threshold:
            failed.append(f"{METRIC_LABELS[key][0]} = {value:.3f} thấp hơn ngưỡng {threshold:.2f}")
    return not failed, failed


def short_text(value: Any, fallback: str = "Chưa có dữ liệu") -> str:
    text = str(value or "").strip()
    return text if text else fallback


def compact_text(value: Any, limit: int = 90) -> str:
    text = " ".join(short_text(value).split())
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def metric_table(
    scores: dict[str, float | None],
    thresholds: dict[str, float],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for key, (label, description) in METRIC_LABELS.items():
        value = scores.get(key)
        threshold = thresholds[key]
        rows.append(
            {
                "Metric": label,
                "Điểm": "n/a" if value is None else f"{value:.3f}",
                "Ngưỡng": f"{threshold:.2f}",
                "Trạng thái": "Thiếu dữ liệu" if value is None else ("PASS" if value >= threshold else "FAIL"),
                "Ý nghĩa": description,
            }
        )
    return rows


def difficulty_counts(cases: list[dict[str, Any]]) -> Counter[str]:
    return Counter(str(case.get("difficulty", "unknown")).lower() for case in cases)


def selected_case_options(cases: list[dict[str, Any]]) -> list[str]:
    options: list[str] = []
    for index, case in enumerate(cases, start=1):
        case_id = case.get("id") or f"CASE-{index:02d}"
        question = str(case.get("question") or "").strip()
        label = question if question else "Chưa điền câu hỏi"
        options.append(f"{case_id} - {label[:90]}")
    return options


def selected_case_id(option: str) -> str:
    return option.split(" - ", 1)[0]


def recommend_cases(
    cases: list[dict[str, Any]],
    benchmark_results: dict[str, dict[str, Any]],
) -> dict[str, str | None]:
    scored = [result for result in benchmark_results.values() if result.get("overall") is not None]
    if not scored:
        first = next((case.get("id") for case in cases if case.get("id")), None)
        return {"Case tốt nhất": first, "Lỗi retrieval": None, "Lỗi generation": None}

    def overall(result: dict[str, Any]) -> float:
        return float(result.get("overall") or 0.0)

    best = max(scored, key=overall).get("id")
    retrieval = min(
        (
            result
            for result in scored
            if result.get("context_recall") is not None
            or result.get("context_precision") is not None
        ),
        key=lambda item: min(
            score_value(item.get("context_recall")) or 1.0,
            score_value(item.get("context_precision")) or 1.0,
        ),
        default=None,
    )
    generation_candidates = [
        result
        for result in scored
        if (score_value(result.get("context_recall")) or 0.0) >= 0.6
        and min(
            score_value(result.get("faithfulness")) or 1.0,
            score_value(result.get("relevance")) or 1.0,
            score_value(result.get("completeness")) or 1.0,
        )
        < 0.6
    ]
    generation = min(
        generation_candidates or scored,
        key=lambda item: min(
            score_value(item.get("faithfulness")) or 1.0,
            score_value(item.get("relevance")) or 1.0,
            score_value(item.get("completeness")) or 1.0,
        ),
    )
    return {
        "Case tốt nhất": str(best) if best else None,
        "Lỗi retrieval": str(retrieval.get("id")) if retrieval else None,
        "Lỗi generation": str(generation.get("id")) if generation else None,
    }


def deterministic_diagnosis(result: dict[str, Any] | None) -> list[str]:
    if not result:
        return ["Chưa có benchmark artifact nên chưa thể chẩn đoán deterministic."]
    recall = score_value(result.get("context_recall"))
    precision = score_value(result.get("context_precision"))
    faithfulness = score_value(result.get("faithfulness"))
    relevance = score_value(result.get("relevance"))
    completeness = score_value(result.get("completeness"))
    notes: list[str] = []
    if recall is not None and recall < 0.5:
        notes.append("Context Recall thấp: retriever có thể đã bỏ sót evidence cần thiết.")
    if recall is not None and precision is not None and recall >= 0.6 and precision < 0.5:
        notes.append("Recall cao nhưng Precision thấp: evidence có tồn tại, nhưng ranking hoặc nhiễu chưa tốt.")
    if (recall or 0.0) >= 0.6 and (precision or 0.0) >= 0.5 and (faithfulness or 1.0) < 0.5:
        notes.append("Retrieval tốt nhưng Faithfulness thấp: phần generation có thể thêm claim không được context support.")
    if (recall or 0.0) >= 0.6 and (completeness or 1.0) < 0.5:
        notes.append("Retrieval tốt nhưng Completeness thấp: LLM có evidence nhưng chưa dùng đủ các ý cần trả lời.")
    if relevance is not None and relevance < 0.5:
        notes.append("Relevance thấp: câu trả lời có thể chưa đúng intent của người hỏi.")
    if not notes:
        notes.append("Chưa thấy pattern lỗi rõ ràng từ các metric hiện có.")
    return notes


def extracted_five_whys(reflection_text: str) -> list[str]:
    markers = ["Symptom", "Why 1", "Why 2", "Why 3", "Why 4", "Why 5"]
    lines = [
        line.strip()
        for line in reflection_text.splitlines()
        if any(marker in line for marker in markers) and "|" in line
    ]
    meaningful = [
        line
        for line in lines
        if not line.endswith("| |")
        and "*Điền:*" not in line
        and "*Câu trả lời:*" not in line
    ]
    return meaningful


def show_header(presentation_mode: bool) -> None:
    st.title("AI Evaluation & Benchmarking")
    st.subheader("Day 14 Demo")
    st.caption("Đo lường -> Chẩn đoán -> Cải thiện -> Chặn regression")
    if presentation_mode:
        st.info("Đang bật Presentation Mode: nội dung được rút gọn để trình bày trong 5-7 phút.")


def show_artifact_status(
    actual: dict[str, Any] | None,
    benchmark: dict[str, Any] | None,
    consistent: bool,
    problems: list[str],
) -> None:
    st.header("Trạng thái dữ liệu demo")
    cols = st.columns(4)
    agent = actual.get("agent", {}) if isinstance(actual, dict) else {}
    summary = benchmark.get("summary", {}) if isinstance(benchmark, dict) else {}
    cols[0].metric("Chế độ", "Artifact")
    cols[1].metric("Model đã sinh", short_text(agent.get("model"), "n/a"))
    cols[2].metric("Số câu", len((actual or {}).get("answers", [])) if isinstance((actual or {}).get("answers", []), list) else 0)
    cols[3].metric("Pass rate", "n/a" if summary.get("pass_rate") is None else f"{summary['pass_rate']:.1%}")
    st.caption(
        "Demo mặc định đọc file đã sinh sẵn, không gọi AI live. Chỉ chạy lại agent khi đổi "
        "golden dataset, prompt, model hoặc muốn cập nhật actual_answers.json."
    )
    if consistent:
        st.success("Artifacts đang khớp với golden_dataset.json hiện tại.")
    else:
        st.error("Artifacts chưa khớp với golden_dataset.json. Cần chạy lại `python domain_assistant.py` và `python evaluate_answers.py`.")
        for problem in problems[:8]:
            st.write(f"- {problem}")


def show_main_demo_flow(
    selected: dict[str, Any],
    actual: dict[str, Any] | None,
    result: dict[str, Any] | None,
    thresholds: dict[str, float],
) -> None:
    st.header("Luồng demo chính")
    st.write(
        "Dùng phần này để trình bày nhanh: chọn một test case, so sánh expected answer "
        "với actual answer, xem metric, chỉnh ngưỡng pass/fail và giải thích nguyên nhân."
    )

    flow_cols = st.columns(5)
    flow_cols[0].metric("Case", short_text(selected.get("id")))
    flow_cols[1].metric("Độ khó", short_text(selected.get("difficulty")))
    flow_cols[2].metric("Overall", format_score((result or {}).get("overall")))
    flow_cols[3].metric("Kết quả gốc", "PASS" if (result or {}).get("passed") else "FAIL")
    flow_cols[4].metric("Failure type", short_text((result or {}).get("failure_type"), "-"))

    st.markdown("**1. Test case đang kiểm tra**")
    st.info(short_text(selected.get("question")))

    expected_col, actual_col = st.columns(2)
    with expected_col:
        st.markdown("**2. Kết quả mong muốn / expected answer**")
        st.write(short_text(selected.get("expected_answer")))
        with st.expander("Evidence chuẩn để chấm"):
            contexts = selected.get("contexts") if isinstance(selected.get("contexts"), list) else []
            for index, context in enumerate(contexts, start=1):
                if not isinstance(context, dict):
                    continue
                st.markdown(f"**{index}. {context.get('source_doc', 'unknown')}**")
                st.write(short_text(context.get("text")))

    with actual_col:
        st.markdown("**3. Câu trả lời thật của hệ thống**")
        if actual is None:
            st.warning("Chưa có actual answer cho case này.")
        else:
            st.write(short_text(actual.get("actual_answer")))
            with st.expander("Context mà retriever đã lấy"):
                retrieved = actual.get("retrieved_contexts") if isinstance(actual.get("retrieved_contexts"), list) else []
                for index, context in enumerate(retrieved, start=1):
                    if not isinstance(context, dict):
                        continue
                    st.markdown(f"**{index}. {context.get('source_doc', 'unknown')} / {context.get('chunk_id', 'chunk')}**")
                    st.write(short_text(context.get("text")))

    st.markdown("**4. Chấm điểm theo ngưỡng đang chọn**")
    scores = result_scores(result)
    passed, failed_reasons = threshold_status(scores, thresholds)
    st.table(metric_table(scores, thresholds))
    if passed:
        st.success("Case này PASS theo ngưỡng đang chọn.")
    else:
        st.error("Case này FAIL theo ngưỡng đang chọn.")
        for reason in failed_reasons:
            st.write(f"- {reason}")

    st.markdown("**5. Lý do để nói khi trình bày**")
    for note in deterministic_diagnosis(result):
        st.write(f"- {note}")
    st.caption(
        "Gợi ý nói: 'Ta không chỉ nhìn overall score. Ta tách retrieval metrics và generation metrics "
        "để biết lỗi nằm ở bước lấy context hay bước sinh câu trả lời.'"
    )


def show_answer_comparison(
    selected: dict[str, Any],
    actual: dict[str, Any] | None,
    result: dict[str, Any] | None,
    show_scores: bool = True,
) -> None:
    st.subheader("Dataset answer vs AI answer")
    st.caption("Bên trái là đáp án chuẩn trong golden dataset. Bên phải là câu trả lời AI đã sinh và được lưu trong artifact.")
    expected_col, actual_col = st.columns(2)
    with expected_col:
        st.markdown("**Đáp án dataset / Expected Answer**")
        st.info(short_text(selected.get("expected_answer")))
    with actual_col:
        st.markdown("**Câu trả lời AI sinh ra / Actual Answer**")
        if actual is None:
            st.warning("Chưa có actual answer cho case này trong artifacts/actual_answers.json.")
        else:
            st.success(short_text(actual.get("actual_answer")))
    if result and show_scores:
        cols = st.columns(4)
        cols[0].metric("Overall", format_score(result.get("overall")))
        cols[1].metric("Faithfulness", format_score(result.get("faithfulness")))
        cols[2].metric("Relevance", format_score(result.get("relevance")))
        cols[3].metric("Completeness", format_score(result.get("completeness")))


def show_compact_metric_groups(result: dict[str, Any] | None) -> None:
    st.subheader("Metric breakdown")
    retrieval_col, generation_col = st.columns(2)
    with retrieval_col:
        st.markdown("**Retrieval metrics**")
        st.caption("Đo bước lấy context: AI đã lấy đúng evidence chưa.")
        cols = st.columns(2)
        cols[0].metric("Context Recall", format_score((result or {}).get("context_recall")))
        cols[1].metric("Context Precision", format_score((result or {}).get("context_precision")))
    with generation_col:
        st.markdown("**Generation metrics**")
        st.caption("Đo câu trả lời cuối: có bám context, đúng trọng tâm và đủ ý không.")
        cols = st.columns(4)
        cols[0].metric("Overall", format_score((result or {}).get("overall")))
        cols[1].metric("Faithfulness", format_score((result or {}).get("faithfulness")))
        cols[2].metric("Relevance", format_score((result or {}).get("relevance")))
        cols[3].metric("Completeness", format_score((result or {}).get("completeness")))


def show_golden_dataset_benchmark_table(
    cases: list[dict[str, Any]],
    result_lookup: dict[str, dict[str, Any]],
    thresholds: dict[str, float],
    row_count: int | None = None,
) -> None:
    visible_cases = cases if row_count is None else cases[:row_count]
    st.header(f"Bảng {len(visible_cases)} Golden Dataset và kết quả benchmark")
    st.write(
        "Màn này dùng để trình bày toàn cảnh: mỗi dòng là một golden test case. "
        "Nhóm cột Retrieval cho biết retriever lấy context tốt chưa. "
        "Nhóm cột LLM Generation cho biết câu trả lời sinh ra có đúng, đủ và bám context không."
    )

    rows: list[dict[str, str]] = []
    for case in visible_cases:
        case_id = str(case.get("id", ""))
        result = result_lookup.get(case_id)
        scores = result_scores(result)
        retrieval_passed, _ = threshold_status(
            {
                "context_recall": scores["context_recall"],
                "context_precision": scores["context_precision"],
            },
            {
                "context_recall": thresholds["context_recall"],
                "context_precision": thresholds["context_precision"],
            },
        )
        generation_passed, _ = threshold_status(
            {
                "faithfulness": scores["faithfulness"],
                "relevance": scores["relevance"],
                "completeness": scores["completeness"],
            },
            {
                "faithfulness": thresholds["faithfulness"],
                "relevance": thresholds["relevance"],
                "completeness": thresholds["completeness"],
            },
        )
        rows.append(
            {
                "ID": case_id,
                "Độ khó": short_text(case.get("difficulty"), "-"),
                "Golden Dataset: câu hỏi": compact_text(case.get("question"), 80),
                "Golden Dataset: expected": compact_text(case.get("expected_answer"), 80),
                "Retrieval: Recall": format_score(scores["context_recall"]),
                "Retrieval: Precision": format_score(scores["context_precision"]),
                "Retrieval: đánh giá": "PASS" if retrieval_passed else "FAIL",
                "LLM Generation: Faithfulness": format_score(scores["faithfulness"]),
                "LLM Generation: Relevance": format_score(scores["relevance"]),
                "LLM Generation: Completeness": format_score(scores["completeness"]),
                "LLM Generation: đánh giá": "PASS" if generation_passed else "FAIL",
                "Overall": format_score((result or {}).get("overall")),
                "Kết luận": "PASS" if retrieval_passed and generation_passed else "Cần phân tích",
            }
        )

    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption(
        "Cách nói: 'Golden Dataset là đề kiểm tra. Retrieval kiểm tra bước lấy evidence. "
        "LLM Generation kiểm tra câu trả lời cuối cùng. Nếu retrieval tốt mà generation fail, lỗi nằm ở LLM/prompt. "
        "Nếu retrieval fail, cần sửa retriever trước.'"
    )


def show_dataset_section(cases: list[dict[str, Any]], selected: dict[str, Any]) -> None:
    st.header("A. Golden Dataset")
    counts = difficulty_counts(cases)
    cols = st.columns(5)
    cols[0].metric("Tổng số case", len(cases))
    cols[1].metric("Easy", counts.get("easy", 0))
    cols[2].metric("Medium", counts.get("medium", 0))
    cols[3].metric("Hard", counts.get("hard", 0))
    cols[4].metric("Adversarial", counts.get("adversarial", 0))
    if not is_filled_case(selected):
        st.warning("Case đang chọn chưa được điền đủ. Đây mới là cấu trúc ground truth.")
    st.write("Đây là ground truth dùng để đánh giá hệ thống AI.")
    st.markdown(f"**Câu hỏi:** {selected.get('question') or 'Chưa điền'}")
    st.markdown(f"**Độ khó:** {selected.get('difficulty') or 'Không rõ'}")
    with st.expander("Expected Answer / Câu trả lời chuẩn"):
        st.write(selected.get("expected_answer") or "Chưa điền")
    with st.expander("Gold Evidence / Gold Context"):
        contexts = selected.get("contexts") if isinstance(selected.get("contexts"), list) else []
        if not contexts:
            st.info("Không tìm thấy gold context.")
        for index, context in enumerate(contexts, start=1):
            source = context.get("source_doc", "unknown") if isinstance(context, dict) else "unknown"
            text = context.get("text", "") if isinstance(context, dict) else ""
            st.markdown(f"**{index}. {source}**")
            st.write(text or "Chưa điền")


def show_system_section(
    selected: dict[str, Any],
    actual: dict[str, Any] | None,
    presentation_mode: bool,
) -> None:
    st.header("B. System Under Đánh giá")
    st.code("Câu hỏi\n  -> Retriever\n  -> Context được retrieve\n  -> LLM\n  -> Câu trả lời thực tế")
    st.caption("Expected answer không được đưa vào RAG system.")
    if actual is None:
        st.warning("Chưa có actual_answers.json nên chưa hiển thị được retrieved context và actual answer.")
        return
    contexts = actual.get("retrieved_contexts") if isinstance(actual.get("retrieved_contexts"), list) else []
    with st.expander("Retrieved Context", expanded=not presentation_mode):
        for index, context in enumerate(contexts, start=1):
            if not isinstance(context, dict):
                continue
            st.markdown(
                f"**{index}. {context.get('source_doc', 'unknown')} "
                f"({context.get('chunk_id', 'chunk')})**"
            )
            st.write(context.get("text", ""))
    st.markdown("**Actual Answer / Câu trả lời thực tế**")
    st.write(actual.get("actual_answer") or "Chưa có câu trả lời đã lưu.")


def show_metrics_section(result: dict[str, Any] | None) -> None:
    st.header("C. Metric Breakdown")
    if result is None:
        st.warning("Chưa có benchmark artifact. Hãy chạy `python evaluate_answers.py` sau khi có actual answers.")
    retrieval, generation = st.columns(2)
    with retrieval:
        st.subheader("Retrieval")
        metric_bar("context_recall", result)
        metric_bar("context_precision", result)
    with generation:
        st.subheader("Generation")
        metric_bar("faithfulness", result)
        metric_bar("relevance", result)
        metric_bar("completeness", result)
    if result and result.get("overall") is not None:
        st.metric("Overall score", format_score(result.get("overall")))


def show_diagnosis_section(result: dict[str, Any] | None) -> None:
    st.header("D. Chẩn đoán")
    for note in deterministic_diagnosis(result):
        st.write(f"- {note}")


def show_failure_analysis_section(
    five_whys_text: str,
    reflection_text: str,
    result: dict[str, Any] | None,
) -> None:
    st.header("E. Failure Analysis / 5 Whys")
    if result and result.get("failure_type"):
        st.metric("Nhóm lỗi", str(result.get("failure_type")))
    else:
        st.info("Case đang chọn chưa có nhóm lỗi.")
    if five_whys_text.strip():
        st.markdown(five_whys_text)
        return
    whys = extracted_five_whys(reflection_text)
    if not whys:
        st.warning("Không tìm thấy dữ liệu 5 Whys trong artifacts/five_whys.md hoặc reflection.md.")
        return
    for line in whys[:12]:
        st.code(line)


def show_engineering_action_section() -> None:
    st.header("F. Hành động kỹ thuật")
    rows = [
        ("Context Recall thấp", "Cải thiện retrieval strategy, query rewriting, chunking, top-k"),
        ("Context Precision thấp", "Thêm reranking, filtering, hoặc scoring chunk tốt hơn"),
        ("Faithfulness thấp", "Siết grounding prompt, citation constraints, yêu cầu dùng context chặt hơn"),
        ("Completeness thấp", "Bổ sung generation instruction hoặc checklist câu trả lời"),
        ("Relevance thấp", "Làm rõ instruction hoặc cải thiện query understanding"),
    ]
    st.table([{"Tín hiệu metric": signal, "Hành động kỹ thuật có thể làm": action} for signal, action in rows])


def show_regression_section(benchmark: dict[str, Any] | None) -> None:
    st.header("G. Regression")
    st.write("Baseline vs Candidate dùng evaluator hiện tại. Nếu metric giảm hơn 0.05 thì xem là regression.")
    if not benchmark:
        st.warning("Chưa có benchmark artifact nên chưa thể so sánh baseline/candidate.")
        return
    summary = benchmark.get("summary") if isinstance(benchmark.get("summary"), dict) else {}
    st.table(
        [
            {"Metric": "Faithfulness", "Baseline": "n/a", "Candidate": format_score(summary.get("avg_faithfulness")), "Delta": "n/a", "Trạng thái": "Cần baseline"},
            {"Metric": "Relevance", "Baseline": "n/a", "Candidate": format_score(summary.get("avg_relevance")), "Delta": "n/a", "Trạng thái": "Cần baseline"},
            {"Metric": "Completeness", "Baseline": "n/a", "Candidate": format_score(summary.get("avg_completeness")), "Delta": "n/a", "Trạng thái": "Cần baseline"},
        ]
    )


def show_pipeline_section() -> None:
    st.header("H. Pipeline cuối")
    st.code(
        "Golden Dataset\n"
        "  -> Chạy AI\n"
        "  -> Đo metric\n"
        "  -> Tìm failure\n"
        "  -> Tìm root cause\n"
        "  -> Sửa\n"
        "  -> Benchmark lại\n"
        "  -> Regression Gate"
    )
    st.success("Đánh giá là một vòng feedback kỹ thuật, không chỉ là điểm số cuối cùng.")


def run_live_case(selected: dict[str, Any], thresholds: dict[str, float]) -> None:
    st.header("Chạy live tuỳ chọn")
    has_key = bool(os.getenv("OPENAI_API_KEY", "").strip())
    model = os.getenv("OPENAI_MODEL", "").strip()
    base_url_configured = bool(os.getenv("OPENAI_BASE_URL", "").strip())
    if not has_key:
        st.info("Không thấy OPENAI_API_KEY trong .env. Demo vẫn chạy được bằng artifact đã lưu.")
        return
    if not model:
        st.info("Không thấy OPENAI_MODEL trong .env. Hãy thêm model trước khi chạy live case.")
        return
    if not is_filled_case(selected):
        st.info("Case đang chọn chưa được điền đủ nên không thể chạy live.")
        return
    endpoint_note = "endpoint tuỳ chỉnh" if base_url_configured else "endpoint OpenAI mặc định"
    st.warning(f"Live run có thể tốn API quota. Model: {model}, endpoint: {endpoint_note}.")
    if st.button("Chạy live case đang chọn"):
        from domain_assistant import DomainAssistant
        from template import RAGASEvaluator

        with st.spinner("Đang chạy một selected case qua DomainAssistant..."):
            assistant = DomainAssistant.from_corpus(CORPUS_DIR)
            response = assistant.answer_with_trace(str(selected["question"]))
        gold_contexts = selected.get("contexts") if isinstance(selected.get("contexts"), list) else []
        gold_texts = [
            str(context.get("text", "")).strip()
            for context in gold_contexts
            if isinstance(context, dict) and str(context.get("text", "")).strip()
        ]
        retrieved_texts = [chunk.text for chunk in response.retrieved_chunks]
        evaluator = RAGASEvaluator()
        live_result = evaluator.run_full_eval(
            answer=response.actual_answer,
            question=str(selected["question"]),
            context="\n\n".join(gold_texts),
            expected=str(selected["expected_answer"]),
            contexts=retrieved_texts,
        )
        live_scores = {
            "context_recall": live_result.context_recall,
            "context_precision": live_result.context_precision,
            "faithfulness": live_result.faithfulness,
            "relevance": live_result.relevance,
            "completeness": live_result.completeness,
        }
        live_passed, live_failed_reasons = threshold_status(live_scores, thresholds)
        st.markdown("**Câu trả lời live**")
        st.write(response.actual_answer)
        st.markdown("**Điểm live theo ngưỡng đang chọn**")
        st.table(metric_table(live_scores, thresholds))
        if live_passed:
            st.success("Live run PASS theo ngưỡng đang chọn.")
        else:
            st.error("Live run FAIL theo ngưỡng đang chọn.")
            for reason in live_failed_reasons:
                st.write(f"- {reason}")
        with st.expander("Retrieved chunks từ live run"):
            for chunk in response.retrieved_chunks:
                st.markdown(f"**{chunk.source_doc} / {chunk.chunk_id}**")
                st.write(chunk.text)


def show_presentation_step(
    step: str,
    selected: dict[str, Any],
    actual: dict[str, Any] | None,
    result: dict[str, Any] | None,
    five_whys_text: str,
) -> None:
    st.header(step)
    if step == "Vấn đề":
        st.write("AI Đánh giá giúp xác định AI sai ở retrieval hay generation.")
        st.write("Mục tiêu là tìm root cause, sửa lỗi, rồi bảo vệ bản sửa bằng regression testing.")
    elif step == "Golden Dataset":
        st.write("Test case đang chọn cung cấp câu hỏi, expected answer và gold evidence.")
        st.markdown(f"**Case:** {selected.get('id')} - {selected.get('difficulty')}")
        st.markdown("**Question**")
        st.write(selected.get("question") or "Chưa điền câu hỏi.")
        show_answer_comparison(selected, actual, result)
    elif step == "Chạy RAG":
        st.code("Câu hỏi -> Retriever -> Context được retrieve -> LLM -> Câu trả lời thực tế")
        st.caption("Expected answer không được đưa vào RAG system.")
        show_answer_comparison(selected, actual, result)
    elif step == "Đánh giá":
        st.write("Retrieval metrics và generation metrics trả lời hai câu hỏi khác nhau.")
        show_answer_comparison(selected, actual, result, show_scores=False)
        show_compact_metric_groups(result)
    elif step == "Chẩn đoán":
        for note in deterministic_diagnosis(result):
            st.write(f"- {note}")
    elif step == "5 Whys":
        st.write("Dùng 5 Whys sau khi metrics cho thấy pattern lỗi.")
        if five_whys_text.strip():
            st.markdown(five_whys_text)
        else:
            st.warning("Chưa có artifacts/five_whys.md.")
    elif step == "Regression":
        st.write("Baseline vs Candidate kiểm tra bản sửa có làm metric quan trọng giảm hơn 0.05 không.")
    elif step == "Kết luận":
        show_pipeline_section()


def main() -> None:
    st.set_page_config(page_title="Day 14 AI Đánh giá Demo", layout="wide")
    golden = read_json(GOLDEN_PATH, file_modified_at(GOLDEN_PATH))
    actual = read_json(ACTUAL_PATH, file_modified_at(ACTUAL_PATH))
    benchmark = read_json(BENCHMARK_PATH, file_modified_at(BENCHMARK_PATH))
    five_whys_text = read_markdown(FIVE_WHYS_PATH, file_modified_at(FIVE_WHYS_PATH))
    reflection_text = read_reflection(REFLECTION_PATH, file_modified_at(REFLECTION_PATH))
    cases = qa_records(golden)
    actual_lookup = answers_by_id(actual)
    result_lookup = results_by_id(benchmark)
    artifacts_consistent, artifact_problems = artifact_consistency(
        cases,
        actual_lookup,
        result_lookup,
    )

    with st.sidebar:
        presentation_mode = st.toggle("Presentation Mode", value=True)
        allow_live = st.toggle("Cho phép chạy AI live", value=False)
        if not cases:
            st.error("Không tìm thấy qa_pairs trong golden_dataset.json.")
            return
        options = selected_case_options(cases)
        selected_label = st.selectbox("Chọn test case", options)
        case_id = selected_case_id(selected_label)
        selected = next(case for case in cases if case.get("id") == case_id)
        recommendations = recommend_cases(cases, result_lookup)
        st.divider()
        st.write("Case gợi ý để trình bày")
        for label, recommended_id in recommendations.items():
            st.caption(f"{label}: {recommended_id or 'chưa đủ dữ liệu'}")
        st.divider()
        st.write("Ngưỡng test")
        default_answer_threshold = 0.5
        default_retrieval_threshold = 0.5
        thresholds = {
            "context_recall": st.slider("Context Recall tối thiểu", 0.0, 1.0, default_retrieval_threshold, 0.05),
            "context_precision": st.slider("Context Precision tối thiểu", 0.0, 1.0, default_retrieval_threshold, 0.05),
            "faithfulness": st.slider("Faithfulness tối thiểu", 0.0, 1.0, default_answer_threshold, 0.05),
            "relevance": st.slider("Relevance tối thiểu", 0.0, 1.0, default_answer_threshold, 0.05),
            "completeness": st.slider("Completeness tối thiểu", 0.0, 1.0, default_answer_threshold, 0.05),
        }
        st.caption("Chỉnh ngưỡng để mô phỏng quality gate khi demo.")
        if presentation_mode:
            step = st.radio("Step", PRESENTATION_STEPS)
        else:
            step = ""

    selected_actual = actual_lookup.get(case_id)
    selected_result = result_lookup.get(case_id)

    show_header(presentation_mode)
    show_artifact_status(actual, benchmark, artifacts_consistent, artifact_problems)
    if presentation_mode:
        show_presentation_step(step, selected, selected_actual, selected_result, five_whys_text)
        return

    if golden and golden.get("_error"):
        st.error(golden["_error"])
    if actual is None:
        st.info("Artifact benchmark chưa được tạo: thiếu artifacts/actual_answers.json.")
    if benchmark is None:
        st.info("Artifact benchmark chưa được tạo: thiếu artifacts/benchmark_results.json.")

    show_main_demo_flow(selected, selected_actual, selected_result, thresholds)
    show_answer_comparison(selected, selected_actual, selected_result)
    show_golden_dataset_benchmark_table(cases, result_lookup, thresholds)
    show_dataset_section(cases, selected)
    show_system_section(selected, selected_actual, presentation_mode)
    show_metrics_section(selected_result)
    show_diagnosis_section(selected_result)
    show_failure_analysis_section(five_whys_text, reflection_text, selected_result)
    show_engineering_action_section()
    show_regression_section(benchmark)
    show_pipeline_section()
    if allow_live:
        with st.expander("Chạy AI live cho một case", expanded=False):
            run_live_case(selected, thresholds)
    else:
        st.info("Live run đang tắt. Bật 'Cho phép chạy AI live' ở sidebar nếu cần test model trực tiếp.")


if __name__ == "__main__":
    main()
