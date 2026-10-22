"""Keep original explicit requests and the established per-product scope."""

import hashlib
import json
import re


def research_questions(detail, product, dimension):
    if dimension != "feature":
        return []
    brief = detail.plan.decision_brief
    text = getattr(brief, "decision_question", "") if brief else ""
    if not text and re.search(r"[?？]|是否|能否|如何|哪些|什么|怎样", detail.topic):
        text = detail.topic
    if not text:
        return []
    products = detail.plan.competitors
    segments = []
    for line in text.splitlines():
        pieces = re.split(r"(?<=[?？])\s*(?=\S)", line)
        if len(pieces) > 1 and not re.search(r"[?？]|是否|能否|如何|哪些|什么|怎样", pieces[-1]):
            pieces[-2:] = [pieces[-2] + pieces[-1]]
        segments.extend(pieces)
    grouped = []
    for segment in segments:
        tail = segment.strip()
        presentation = re.fullmatch(r"请将[^?？\n]*(?:分别|逐项)(?:说明|列出|展示)[。.!]?", tail)
        if (grouped and presentation
                and not any(name in tail and name not in grouped[-1] for name in products)):
            grouped[-1] += " " + tail
        else:
            grouped.append(segment)
    result, seen, active_products = [], set(), []
    for line in grouped:
        question = re.sub(r"^\s*(?:[-*]|\d+[.)、])\s*", "", line).strip()
        if not question or question in seen:
            continue
        mentioned = [
            name
            for name in products
            if re.search(
                r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])"
                if name.isascii()
                else re.escape(name),
                question,
                re.I,
            )
        ]
        if mentioned:
            active_products = mentioned
        if active_products and product not in active_products:
            continue
        seen.add(question)
        question_id = hashlib.sha256(
            json.dumps([product, dimension, question], ensure_ascii=False).encode()
        ).hexdigest()[:20]
        result.append({"question_id": f"question-{question_id}", "question": question})
    return result
