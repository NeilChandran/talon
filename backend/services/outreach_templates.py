"""Ready-to-send outreach copy from the user's ICP prompt."""
import re
from typing import Any, Dict


def wants_founders(prompt: str) -> bool:
    pl = prompt.lower()
    return any(w in pl for w in ("founder", "founders", "co-founder", "cofounder", "ceo"))


def _product_hint(prompt: str) -> str:
    pl = prompt.lower()
    if "saas" in pl or "b2b" in pl:
        return "B2B SaaS"
    if "yc" in pl:
        return "YC startup"
    return "what you're building"


def personalize(template: str, *, first_name: str = "", company: str = "", title: str = "") -> str:
    fn = first_name.strip() or "there"
    co = company.strip() or "your company"
    ti = title.strip() or "founder"
    out = template
    for key, val in (
        ("{{first_name}}", fn),
        ("{{company}}", co),
        ("{{title}}", ti),
    ):
        out = out.replace(key, val)
    return out


def build_outreach_kit(prompt: str, linkedin_template: str = "") -> Dict[str, Any]:
    """Templates for LinkedIn + email — filled per lead in the API/UI."""
    founders = wants_founders(prompt)
    product = _product_hint(prompt)

    if linkedin_template.strip():
        linkedin = linkedin_template.strip()
    elif founders:
        linkedin = (
            "Hi {{first_name}} — I'm reaching out to a few YC founders building {{company}}. "
            f"Would love to hear how you're thinking about {product} and share what we're working on. "
            "Open to a quick chat?"
        )
        email_subject = "YC founder → quick intro ({{company}})"
        email_body = (
            "Hi {{first_name}},\n\n"
            "I'm connecting with founders building B2B products post-YC — {{company}} stood out.\n\n"
            f"I'd love to learn more about your roadmap and share how we help teams like yours with {product}.\n\n"
            "Worth a 15-min call this week?\n\n"
            "Best"
        )
    else:
        linkedin = (
            "Hi {{first_name}} — saw your work at {{company}} and wanted to reach out. "
            f"Building something for teams in {product} — would value your perspective. "
            "Open to connect?"
        )
        email_subject = "Quick intro — {{company}}"
        email_body = (
            "Hi {{first_name}},\n\n"
            "I came across {{company}} and thought there could be a fit.\n\n"
            f"We help with {product} — happy to share more if useful.\n\n"
            "Best"
        )

    return {
        "linkedin_connection": linkedin,
        "email_subject": email_subject,
        "email_step1": email_body,
        "email_step2": (
            "Hi {{first_name}},\n\n"
            "Following up — still think this could be valuable for {{company}}. "
            "Let me know if you'd like a quick overview.\n\n"
            "Best"
        ),
        "email_step3": (
            "Hi {{first_name}},\n\n"
            "Last note from me — happy to connect whenever timing works at {{company}}.\n\n"
            "Best"
        ),
        "channel_hint": "linkedin" if "linkedin" in prompt.lower() else "email",
        "targets_founders": founders,
    }
