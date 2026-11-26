"""Create illustration requests only for knowledge-base portions or actions.

A picture may show the portion or action already written in a read source,
for example "half a medium apple" when that phrase comes from the knowledge
base. It must not invent a food, a quantity, or a movement in order to fill
the page. Classification pictures such as "good fruit / bad fruit" are not
allowed. Prompts must not ask for medicine-box trademarks, faces, or
identity details.
"""

from __future__ import annotations

from .models import AdviceItem, IllustrationRequest

# Phrases that would add content the knowledge base did not state, or that
# would violate the illustration rules.
FORBIDDEN_PROMPT_FRAGMENTS = (
    "好水果",
    "坏水果",
    "可以吃的水果",
    "不能吃的水果",
    "药盒",
    "商标",
    "logo",
    "品牌",
    "患者面部",
    "人脸",
    "姓名",
    "电话",
    "病历号",
)

FORBIDDEN_EXTRA_FOOD_HINTS = (
    "再摆",
    "再加",
    "再配",
    "一整盘",
    "一盘",
    "装饰",
)


def request_illustration(item: AdviceItem) -> IllustrationRequest:
    """Return an allowed request, or a refused request with a reason."""
    portion = (item.portion_or_action or "").strip()
    if item.category not in {"diet", "activity"}:
        return _refused(item, portion, "只有具体的饮食或运动建议才考虑配图。")
    if not portion:
        return _refused(
            item,
            portion,
            "知识库没有写明可图解的份量或动作，不能为了配图而编造食物、份量或动作。",
        )
    caption = portion
    prompt = _build_prompt(portion)
    reason = _refusal_reason(prompt)
    if reason:
        return _refused(item, portion, reason, prompt=prompt, caption=caption)
    return IllustrationRequest(
        advice_entry_id=None,
        portion_or_action=portion,
        caption=caption,
        prompt=prompt,
        allowed=True,
        refusal_reason=None,
    )


def attach_illustrations(items: list[AdviceItem]) -> list[AdviceItem]:
    for item in items:
        if item.category in {"diet", "activity"}:
            item.illustration = request_illustration(item)
    return items


def _build_prompt(portion_or_action: str) -> str:
    return (
        "绘制一张简单、干净的示意图，只表现下列知识库已经写明的份量或动作，"
        "不要增加其他食物、餐具堆叠、人物面部或药品包装："
        f"{portion_or_action}"
    )


def _refusal_reason(prompt: str) -> str | None:
    lowered = prompt.lower()
    for fragment in FORBIDDEN_PROMPT_FRAGMENTS:
        if fragment.lower() in lowered:
            return f"配图说明包含不允许的内容（{fragment}）。"
    # The allowed prompt includes the portion text only once after a fixed
    # prefix. Extra staging instructions are rejected if a caller bypasses
    # _build_prompt and sends a custom prompt through validate_custom_prompt.
    return None


def validate_custom_prompt(portion_or_action: str, custom_prompt: str) -> IllustrationRequest:
    """Reject a hand-written prompt that adds foods, portions, or forbidden content.

    The first version does not call an image model. This helper exists so
    tests and later image backends can share the same rule: the knowledge-base
    portion or action must appear, and the prompt must not add extras.
    """
    portion = (portion_or_action or "").strip()
    if not portion:
        return IllustrationRequest(
            advice_entry_id=None,
            portion_or_action=portion,
            caption="",
            prompt=custom_prompt,
            allowed=False,
            refusal_reason="没有知识库份量或动作原文，不能生成配图。",
        )
    if portion not in custom_prompt:
        return IllustrationRequest(
            advice_entry_id=None,
            portion_or_action=portion,
            caption=portion,
            prompt=custom_prompt,
            allowed=False,
            refusal_reason="配图说明没有完整包含知识库中的份量或动作原文。",
        )
    for hint in FORBIDDEN_EXTRA_FOOD_HINTS:
        if hint in custom_prompt:
            return IllustrationRequest(
                advice_entry_id=None,
                portion_or_action=portion,
                caption=portion,
                prompt=custom_prompt,
                allowed=False,
                refusal_reason=f"配图说明试图增加知识库未写明的元素（{hint}），已拒绝。",
            )
    reason = _refusal_reason(custom_prompt)
    if reason:
        return IllustrationRequest(
            advice_entry_id=None,
            portion_or_action=portion,
            caption=portion,
            prompt=custom_prompt,
            allowed=False,
            refusal_reason=reason,
        )
    return IllustrationRequest(
        advice_entry_id=None,
        portion_or_action=portion,
        caption=portion,
        prompt=custom_prompt,
        allowed=True,
        refusal_reason=None,
    )


def _refused(
    item: AdviceItem,
    portion: str,
    reason: str,
    *,
    prompt: str = "",
    caption: str = "",
) -> IllustrationRequest:
    return IllustrationRequest(
        advice_entry_id=None,
        portion_or_action=portion,
        caption=caption,
        prompt=prompt,
        allowed=False,
        refusal_reason=reason,
    )
