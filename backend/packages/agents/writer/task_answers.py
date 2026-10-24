"""Compile request segments and display only credentialed local task decisions."""

from __future__ import annotations

import json

from packages.schema.decision_brief import safe_decision_brief_text as plain

TASK_ANSWER_REQUEST_BYTES = 10000
TASK_ANSWER_RESERVE = 12000


def task_answer_plan(questions, tasks, supported_ids):
    """Propose a lossless request partition; this is not coverage approval."""
    plans = []
    for q in questions:
        text = q["question"]
        located = []
        for task in tasks:
            quote = task.get("question_quote", "")
            if (
                task.get("question_id") != q["question_id"]
                or not quote
                or task.get("focus", "").startswith("rule_")
                or text.count(quote) != 1
            ):
                continue
            start = text.index(quote)
            located.append((start, start + len(quote), task))
        groups = []
        for start, end, task in sorted(located, key=lambda row: (row[0], row[1])):
            if groups and start < groups[-1][1]:
                groups[-1][1] = max(end, groups[-1][1])
                groups[-1][2].append(task)
            else:
                groups.append([start, end, [task]])
        if not groups:
            groups = [[0, len(text), []]]
        previous, parts = 0, []
        for i, (_, end, members) in enumerate(groups):
            stop = len(text) if i == len(groups) - 1 else end
            selected = [
                t
                for t in members
                if t.get("state") == "supported"
                and t.get("claim_id") in supported_ids
                and t.get("decision")
            ]
            conclusions = {t["decision"]["conclusion"] for t in selected}
            complete = bool(members) and len(selected) == len(members)
            conclusion = (
                (next(iter(conclusions)) if len(conclusions) == 1 else "depends")
                if complete
                else "unknown"
            )
            relations = {t["decision"]["relation"] for t in selected}
            parts.append(
                dict(
                    segment_id=f"segment-{i}",
                    question_quote=text[previous:stop],
                    claim_ids=list(dict.fromkeys(t["claim_id"] for t in selected)),
                    conclusion=conclusion,
                    relation=next(iter(relations))
                    if complete and len(relations) == 1
                    else "unresolved",
                )
            )
            previous = stop
        from packages.research.question_state import question_state

        plans.append(
            dict(
                question_id=q["question_id"],
                subquestions=parts,
                delivery_state=question_state(
                    q,
                    reviewed_tasks=[
                        t
                        for t in tasks
                        if t.get("question_id") == q["question_id"]
                        and t.get("state") == "supported"
                        and t.get("claim_id") in supported_ids
                    ],
                ),
            )
        )
    return plans


def restore_task_segments(response, plans):
    """Expand only server-issued segment IDs; invalid peers remain invalid."""
    try:
        parsed = json.loads(response)
        known = {
            p["question_id"]: {s["segment_id"]: s["question_quote"] for s in p["subquestions"]}
            for p in plans
        }
        parsed["answers"] = [
            a
            for a in parsed["answers"]
            if isinstance(a, dict) and isinstance(a.get("question_id"), str)
        ]
        for answer in parsed["answers"]:
            if not isinstance(answer, dict) or not isinstance(answer.get("question_id"), str):
                continue
            rows = answer.get("subquestions")
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                continue
            if any(
                set(row) != {"segment_id", "claim_ids", "conclusion", "relation"} for row in rows
            ):
                # A model-authored replacement partition cannot bypass server IDs.
                answer["subquestions"] = []
                continue
            ids = [row["segment_id"] for row in rows]
            scope = known.get(answer.get("question_id"), {})
            if ids != list(scope):
                continue
            answer["subquestions"] = [
                dict(
                    question_quote=scope[row["segment_id"]],
                    **{k: v for k, v in row.items() if k != "segment_id"},
                )
                for row in rows
            ]
        return json.dumps(parsed, ensure_ascii=False)
    except (TypeError, ValueError, KeyError, AttributeError):
        return response


def reviewed_task_answer_rows(detail, audit):
    from packages.agents.writer.task_projection import reviewed_task_results

    supported = {item.claim.id: item.claim for item in audit.claims if item.status == "supported"}
    return [
        dict(
            task_id=t["task_id"],
            question_id=t["question_id"],
            question=t["question"],
            question_quote=t["question_quote"],
            resource=t.get("resource"),
            state="supported",
            focus=t["focus"],
            conclusion=t["decision"]["conclusion"],
            relation=t["decision"]["relation"],
            claim_id=t["claim_id"],
            claim=supported[t["claim_id"]].model_dump(mode="json"),
        )
        for t in reviewed_task_results(detail, audit)
        if not t["focus"].startswith("rule_")
    ]


def task_answer_lines(rows, language):
    zh = language.startswith("zh")
    labels = {"yes": "是", "no": "否", "depends": "按条件判断", "not_applicable": "不适用"}
    lines = []
    for row in rows:
        resource = (
            f"（对象：{plain(row['resource'])}）"
            if row.get("resource") and zh
            else (f" (resource: {plain(row['resource'])})" if row.get("resource") else "")
        )
        label = labels[row["conclusion"]] if zh else row["conclusion"]
        lines.append(
            f"  - 子任务结论：{label}{resource}；仅针对上述题设的“{plain(row['question_quote'])}”。"
            if zh
            else (f"  - Reviewed task conclusion: {label}{resource}; "
                  f"for the above request: {plain(row['question_quote'])}")
        )
        citations = "".join(f"[source:{sid}]" for sid in row["claim"]["source_ids"])
        lines.append(
            f"    {'依据' if zh else 'Support'}：{plain(row['claim']['text'])} {citations}"
        )
    return lines
